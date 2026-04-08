import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';

export interface DistributionProps {
  environment: string;
  functionUrlDomain: string;
  webAclArn: string;
}

export class Distribution extends Construct {
  public readonly distribution: cloudfront.Distribution;
  public readonly frontendBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: DistributionProps) {
    super(scope, id);

    // S3 bucket for static frontend assets (private, OAC access only)
    this.frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `illuminate-frontend-${props.environment}-${cdk.Aws.ACCOUNT_ID}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // SPA routing function — rewrites non-file paths to /index.html
    const spaFunction = new cloudfront.Function(this, 'SpaRouting', {
      functionName: `illuminate-spa-routing-${props.environment}`,
      code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.includes('.')) {
    return request;
  }
  request.uri = '/index.html';
  return request;
}
      `.trim()),
      runtime: cloudfront.FunctionRuntime.JS_2_0,
    });

    // S3 origin with OAC (CDK auto-creates the OAC and bucket policy)
    const s3Origin = origins.S3BucketOrigin.withOriginAccessControl(this.frontendBucket);

    // Lambda Function URL origin (API)
    const apiOrigin = new origins.HttpOrigin(props.functionUrlDomain, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
      httpsPort: 443,
    });

    // Managed cache/origin-request policies (by AWS-managed policy ID)
    const cachingDisabled = cloudfront.CachePolicy.fromCachePolicyId(
      this, 'CachingDisabled', '4135ea2d-6df8-44a3-9df3-4b5a84be39ad',
    );
    const allViewerExceptHost = cloudfront.OriginRequestPolicy.fromOriginRequestPolicyId(
      this, 'AllViewerExceptHost', 'b689b0a8-53d0-40ab-baf2-68738e2966ac',
    );

    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      webAclId: props.webAclArn,
      defaultBehavior: {
        origin: s3Origin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
        compress: true,
        functionAssociations: [
          {
            function: spaFunction,
            eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
          },
        ],
      },
      additionalBehaviors: {
        '/api/*': {
          origin: apiOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
          cachePolicy: cachingDisabled,
          originRequestPolicy: allViewerExceptHost,
          compress: true,
        },
        '/health': {
          origin: apiOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
          cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
          cachePolicy: cachingDisabled,
          originRequestPolicy: allViewerExceptHost,
        },
      },
    });
  }

  get cloudFrontUrl(): string {
    return `https://${this.distribution.distributionDomainName}`;
  }
}
