# EC2 Instance Events Handler

AWS Lambda handler that:
* adds/updates automatically Route53 local zone DNS entry for each started EC2 instance
* removes Route53 local zone DNS entry and disables monitoring of the EC2 instance on Zabbix

# Dependencies

```
$ pip install pyzabbix -t .
```

# Deployment

```
$ zip -r ../ec2_event_handler.zip *
$ cd ..
$ aws lambda update-function-code --function-name ec2_event_handler --zip-file fileb://$(pwd)/ec2_event_handler.zip --publish
```
