import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface AgentRoleProps {
  environment: string;
  snowflakeSecretArn: string;
}

export class AgentRole extends Construct {
  public readonly role: iam.Role;

  constructor(scope: Construct, id: string, props: AgentRoleProps) {
    super(scope, id);

    this.role = new iam.Role(this, 'Role', {
      roleName: `illuminate-agent-role-${props.environment}`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'Execution role for Illuminate AgentCore agents',
    });

    // Bedrock model invocation
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream',
      ],
      resources: [
        'arn:aws:bedrock:*::foundation-model/anthropic.claude-*',
        `arn:aws:bedrock:*:${cdk.Aws.ACCOUNT_ID}:inference-profile/us.anthropic.claude-*`,
      ],
    }));

    // Snowflake credentials
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [props.snowflakeSecretArn],
    }));

    // CloudWatch Logs
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: [
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
      ],
      resources: [
        `arn:aws:logs:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/*`,
      ],
    }));

    // AgentCore cross-agent invocation
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeAgentRuntime'],
      resources: [
        `arn:aws:bedrock-agentcore:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:runtime/illuminate_*`,
      ],
    }));

    // AgentCore Memory (STM) operations
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: [
        'bedrock-agentcore:ListEvents',
        'bedrock-agentcore:CreateEvent',
        'bedrock-agentcore:GetEvent',
        'bedrock-agentcore:ListSessions',
        'bedrock-agentcore:CreateSession',
        'bedrock-agentcore:GetSession',
      ],
      resources: [
        `arn:aws:bedrock-agentcore:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:memory/illuminate_*`,
      ],
    }));

    // S3 access for CodeBuild sources
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:GetBucketLocation', 's3:ListBucket'],
      resources: [
        `arn:aws:s3:::bedrock-agentcore-codebuild-sources-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}`,
        `arn:aws:s3:::bedrock-agentcore-codebuild-sources-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}/*`,
      ],
    }));

    // ECR access for container images
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: [
        'ecr:GetAuthorizationToken',
        'ecr:BatchGetImage',
        'ecr:GetDownloadUrlForLayer',
      ],
      resources: ['*'],
    }));
  }
}
