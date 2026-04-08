import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Networking } from './networking';
import { Auth } from './auth';
import { Storage } from './storage';
import { Waf } from './waf';
import { Discovery } from './discovery';

export interface BaseStackProps extends cdk.StackProps {
  environment: string;
  snowflakeAccount: string;
  snowflakeUser: string;
  snowflakePassword: string;
  snowflakeDatabase: string;
  snowflakeWarehouse: string;
  snowflakeRole: string;
}

export class BaseStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly securityGroup: ec2.SecurityGroup;
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly artifactsBucket: s3.Bucket;
  public readonly snowflakeSecret: secretsmanager.Secret;
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: BaseStackProps) {
    super(scope, id, props);

    const isProd = props.environment === 'prod';

    const networking = new Networking(this, 'Networking', {
      environment: props.environment,
    });
    this.vpc = networking.vpc;
    this.securityGroup = networking.securityGroup;

    const auth = new Auth(this, 'Auth', {
      environment: props.environment,
    });
    this.userPool = auth.userPool;
    this.userPoolClient = auth.userPoolClient;

    const storage = new Storage(this, 'Storage', {
      environment: props.environment,
      snowflakeAccount: props.snowflakeAccount,
      snowflakeUser: props.snowflakeUser,
      snowflakePassword: props.snowflakePassword,
      snowflakeDatabase: props.snowflakeDatabase,
      snowflakeWarehouse: props.snowflakeWarehouse,
      snowflakeRole: props.snowflakeRole,
    });
    this.artifactsBucket = storage.artifactsBucket;
    this.snowflakeSecret = storage.snowflakeSecret;

    const waf = new Waf(this, 'Waf', {
      environment: props.environment,
      isProd,
      scope: 'REGIONAL',
    });
    this.webAclArn = waf.webAclArn;

    // Publish discovery parameters to SSM
    new Discovery(this, 'Discovery', {
      environment: props.environment,
      parameters: {
        'cognito-pool-id': auth.userPool.userPoolId,
        'cognito-client-id': auth.userPoolClient.userPoolClientId,
        'artifacts-bucket': storage.artifactsBucket.bucketName,
        'snowflake-secret-arn': storage.snowflakeSecret.secretArn,
      },
    });
  }
}
