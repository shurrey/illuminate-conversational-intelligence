import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';

export interface StorageProps {
  environment: string;
  snowflakeAccount: string;
  snowflakeUser: string;
  snowflakePassword: string;
  snowflakeDatabase: string;
  snowflakeWarehouse: string;
  snowflakeRole: string;
}

export class Storage extends Construct {
  public readonly artifactsBucket: s3.Bucket;
  public readonly snowflakeSecret: secretsmanager.Secret;

  constructor(scope: Construct, id: string, props: StorageProps) {
    super(scope, id);

    this.artifactsBucket = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `illuminate-artifacts-${props.environment}-${cdk.Aws.ACCOUNT_ID}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.snowflakeSecret = new secretsmanager.Secret(this, 'SnowflakeSecret', {
      secretName: `illuminate/${props.environment}/snowflake`,
      description: 'Snowflake connection credentials',
      secretStringValue: cdk.SecretValue.unsafePlainText(JSON.stringify({
        account: props.snowflakeAccount,
        user: props.snowflakeUser,
        password: props.snowflakePassword,
        database: props.snowflakeDatabase,
        warehouse: props.snowflakeWarehouse,
        role: props.snowflakeRole,
      })),
    });
  }
}
