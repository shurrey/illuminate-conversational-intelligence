import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { LambdaProxy } from './lambda-proxy';

export interface ApiStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  securityGroup: ec2.ISecurityGroup;
  orchestratorArn: string;
  userPoolId: string;
  userPoolClientId: string;
  artifactsBucketName: string;
  snowflakeSecretArn: string;
  frontendOrigin?: string;
}

export class ApiStack extends cdk.Stack {
  public readonly functionUrl: lambda.FunctionUrl;
  public readonly functionUrlDomain: string;
  public readonly lambdaFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const proxy = new LambdaProxy(this, 'LambdaProxy', {
      environment: props.environment,
      vpc: props.vpc,
      securityGroup: props.securityGroup,
      orchestratorArn: props.orchestratorArn,
      userPoolId: props.userPoolId,
      userPoolClientId: props.userPoolClientId,
      artifactsBucketName: props.artifactsBucketName,
      snowflakeSecretArn: props.snowflakeSecretArn,
      frontendOrigin: props.frontendOrigin,
    });

    this.functionUrl = proxy.functionUrl;
    this.functionUrlDomain = proxy.functionUrlDomain;
    this.lambdaFunction = proxy.fn;
  }
}
