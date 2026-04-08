#!/usr/bin/env npx ts-node
import * as cdk from 'aws-cdk-lib';
import { BaseStack } from '../lib/base';
import { AgentCoreStack } from '../lib/agentcore';
import { ApiStack } from '../lib/api';
import { FrontendStack } from '../lib/frontend';

const app = new cdk.App();

// Environment from CDK context: cdk deploy -c environment=dev
const environment = app.node.tryGetContext('environment') || 'dev';

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// =============================================================================
// Stack 1: Base infrastructure (VPC, Cognito, S3, Secrets, WAF)
// =============================================================================
const base = new BaseStack(app, `IlluminateBase-${environment}`, {
  env,
  environment,
  // Snowflake credentials — pass via context or environment variables.
  // For initial setup: cdk deploy -c snowflakeAccount=xxx -c snowflakePassword=xxx ...
  // After creation, the secret is managed in Secrets Manager directly.
  snowflakeAccount: app.node.tryGetContext('snowflakeAccount') || '',
  snowflakeUser: app.node.tryGetContext('snowflakeUser') || 'SVC_BLACKBOARD_DATA',
  snowflakePassword: app.node.tryGetContext('snowflakePassword') || '',
  snowflakeDatabase: app.node.tryGetContext('snowflakeDatabase') || '',
  snowflakeWarehouse: app.node.tryGetContext('snowflakeWarehouse') || 'BLACKBOARD_DATA_WH',
  snowflakeRole: app.node.tryGetContext('snowflakeRole') || 'BBDATA_USER_ROLE',
});

// =============================================================================
// Stack 2: AgentCore (IAM, Gateway, Memory, 5x Agent Runtimes)
// =============================================================================
const agentcore = new AgentCoreStack(app, `IlluminateAgentCore-${environment}`, {
  env,
  environment,
  snowflakeSecret: base.snowflakeSecret,
});
agentcore.addDependency(base);

// =============================================================================
// Stack 3: API proxy (Lambda + LWA + Function URL)
// =============================================================================
const api = new ApiStack(app, `IlluminateApi-${environment}`, {
  env,
  environment,
  vpc: base.vpc,
  securityGroup: base.securityGroup,
  orchestratorArn: agentcore.orchestratorArn,
  userPoolId: base.userPool.userPoolId,
  userPoolClientId: base.userPoolClient.userPoolClientId,
  artifactsBucketName: base.artifactsBucket.bucketName,
  snowflakeSecretArn: base.snowflakeSecret.secretArn,
});
api.addDependency(agentcore);

// =============================================================================
// Stack 4: Frontend (S3 + CloudFront + WAF)
// =============================================================================
const frontend = new FrontendStack(app, `IlluminateFrontend-${environment}`, {
  env,
  environment,
  functionUrlDomain: api.functionUrlDomain,
});
frontend.addDependency(api);

app.synth();
