#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { IlluminateAgentsStack } from '../lib/illuminate-agents-stack';

const app = new cdk.App();

// Development stack
new IlluminateAgentsStack(app, 'IlluminateDev', {
  environment: 'dev',
  allowedOrigins: ['http://localhost:3000', 'http://localhost:5173'],
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || 'us-east-1'
  },
  tags: {
    Project: 'Illuminate',
    Environment: 'dev'
  }
});

# Production stack (deploy separately)
new IlluminateAgentsStack(app, 'IlluminateProd', {
  environment: 'prod',
  snowflakeAccount: process.env.SNOWFLAKE_ACCOUNT,
  domainName: process.env.DOMAIN_NAME,
  certificateArn: process.env.CERTIFICATE_ARN,
  allowedOrigins: process.env.ALLOWED_ORIGINS?.split(',') || ['https://illuminate.anthology.com'],
  institutionIdpUrl: process.env.INSTITUTION_IDP_URL,
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1'
  },
  tags: {
    Project: 'Illuminate',
    Environment: 'prod',
    SecurityLevel: 'high'
  }
});
