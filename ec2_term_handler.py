from __future__ import print_function

import time
import json
import boto3
from pyzabbix import ZabbixAPI

zabbix_api = 'http://myzabbixserver.com/zabbix'
zabbix_user = 'ec2manager'
zabbix_pass = 'mypass'

dns_zone_id = 'ID-OF-THE-ZONE-ON-ROUTE53'

print('Loading function')


def init_session():
    s = boto3.session.Session()

    return s


def init_ec2():
    s = init_session()
    return s.resource('ec2')


def init_route53():
    return boto3.client('route53')


def get_dns_zone_name(zone_id):
    try:
        route53 = init_route53()
        response = route53.get_hosted_zone(Id=zone_id)
        return response['HostedZone']['Name']
    except Exception as e:
        print("route53_zone_name ERROR: %s" % str(e))
    return None


dns_zone = get_dns_zone_name(dns_zone_id)


def get_instance_name(instance):
    try:
        for itag in instance.tags:
            if itag['Key'] == 'Name':
                return itag['Value']
    except Exception as e:
        print("get_instance_name ERROR: %s" % str(e))
    return None


def find_instance(instance_id):
    print("Looking for instance: %s" % instance_id)
    try:
        count = 0
        while(count < 20):
            ec2 = init_ec2()
            for i in ec2.instances.all():
                if i.id == instance_id:
                    print(i)
                    instance_name = get_instance_name(i)
                    instance_ip = i.private_ip_address
                    if instance_name:
                        print("Found instance %s with ip %s" %
                              (instance_name, instance_ip))
                        return (instance_name, instance_ip)
            time.sleep(30)
            count += 1
    except Exception as e:
        print("find_instance ERROR: %s" % str(e))
    print("There is no instance %s" % instance_id)
    return (None, None)


def get_ip_address_from_dns(fqdn):
    try:
        route53 = init_route53()
        response = route53.list_resource_record_sets(HostedZoneId=dns_zone_id)
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            for rrset in response['ResourceRecordSets']:
                if rrset['Name'].lower() == fqdn.lower():
                    return rrset['ResourceRecords'][0]['Value']
    except Exception as e:
        print("Error getting ip address: %s" % str(e))
    return None


def add_dns_record(instance_name, instance_ip):
    fqdn = instance_name + '.' + dns_zone

    current_ip = get_ip_address_from_dns(fqdn)

    if current_ip:
        if current_ip == instance_ip:
            return None
        else:
            remove_dns_record(instance_name)

    print("Adding DNS record for: [%s] [%s]" % (fqdn, instance_ip))

    response = None
    try:
        route53 = init_route53()
        response = route53.change_resource_record_sets(
            HostedZoneId=dns_zone_id,
            ChangeBatch={
                'Comment': 'comment',
                'Changes': [
                    {
                        'Action': 'CREATE',
                        'ResourceRecordSet': {
                            'Name': fqdn,
                            'Type': 'A',
                            'TTL': 60,
                            'ResourceRecords': [
                                {
                                    'Value': instance_ip
                                },
                            ],
                        }
                    },
                ]
            }
        )
    except Exception as e:
        print("Route53 error: %s" % str(e))
    else:
        print("RESPONSE:", response)
    return response


def remove_dns_record(instance_name):
    fqdn = instance_name + '.' + dns_zone
    instance_ip = get_ip_address_from_dns(fqdn)

    print("Removing DNS record for: [%s] [%s]" % (fqdn, instance_ip))

    response = None
    if not instance_ip:
        print("Can't find ip address in DNS for %s, skipping." % fqdn)
        return response

    try:
        route53 = init_route53()
        response = route53.change_resource_record_sets(
            HostedZoneId=dns_zone_id,
            ChangeBatch={
                'Comment': 'comment',
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': {
                            'Name': fqdn,
                            'Type': 'A',
                            'TTL': 60,
                            'ResourceRecords': [
                                {
                                    'Value': instance_ip
                                },
                            ],
                        }
                    },
                ]
            }
        )
    except Exception as e:
        print("Route53 error: %s" % str(e))
    else:
        print("RESPONSE:", response)
    return response


def disable_on_zabbix(instance_name):
    zapi = ZabbixAPI(zabbix_api)
    zapi.login(zabbix_user, zabbix_pass)

    hosts = zapi.host.get(filter={
        "name": instance_name
    })
    if len(hosts) > 0 and 'hostid' in hosts[0]:
        hostid = hosts[0]['hostid']
        print("Disabling on Zabbix: %s %s" %
              (instance_name, hostid))
        zapi.host.update(hostid=hostid, status=1)


def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))

    if 'region' in event and 'detail' in event:
        detail = event['detail']
        if 'state' in detail and 'instance-id' in detail:
            instance_id = detail['instance-id']
            if detail['state'] == 'terminated':
                print("Termination of EC2 instance [%s] detected."
                      " Let's cleanup!" % instance_id)

                instance_name, instance_ip = find_instance(instance_id)

                if not instance_name:
                    print("Failed to figure out instance name")
                else:
                    print("DETAILS - instance_id: [%s]"
                          " instance_name: [%s]"
                          " instance_ip: [%s]" %
                          (instance_id, instance_name, instance_ip))

                    disable_on_zabbix(instance_name)
                    remove_dns_record(instance_name)

            elif detail['state'] == 'running':
                print("Startup of EC2 instance [%s] detected."
                      " Let's go!" % instance_id)

                instance_name, instance_ip = find_instance(instance_id)

                if not instance_name:
                    print("Failed to figure out instance name")
                elif not instance_ip:
                    print("Failed to figure out instance ip address")
                else:
                    print("DETAILS - instance_id: [%s]"
                          " instance_name: [%s]"
                          " instance_ip: [%s]" %
                          (instance_id, instance_name, instance_ip))

                    add_dns_record(instance_name, instance_ip)
