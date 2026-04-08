import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import { Waf } from '../base/waf';
import { Distribution } from './distribution';

export interface FrontendStackProps extends cdk.StackProps {
  environment: string;
  functionUrlDomain: string;
}

export class FrontendStack extends cdk.Stack {
  public readonly distribution: cloudfront.Distribution;
  public readonly frontendBucket: s3.Bucket;
  public readonly cloudFrontUrl: string;

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    super(scope, id, props);

    const isProd = props.environment === 'prod';

    // CloudFront-scoped WAF (must be in us-east-1)
    const waf = new Waf(this, 'Waf', {
      environment: props.environment,
      isProd,
      scope: 'CLOUDFRONT',
      commonRuleExclusions: ['SizeRestrictions_BODY'],
    });

    const dist = new Distribution(this, 'Distribution', {
      environment: props.environment,
      functionUrlDomain: props.functionUrlDomain,
      webAclArn: waf.webAclArn,
    });

    this.distribution = dist.distribution;
    this.frontendBucket = dist.frontendBucket;
    this.cloudFrontUrl = dist.cloudFrontUrl;

    // Outputs
    new cdk.CfnOutput(this, 'CloudFrontURL', {
      value: dist.cloudFrontUrl,
      description: 'CloudFront distribution URL',
    });

    new cdk.CfnOutput(this, 'FrontendBucketName', {
      value: dist.frontendBucket.bucketName,
      description: 'S3 bucket for frontend assets',
    });
  }
}
