#!/bin/bash
set -e

ENVIRONMENT=${1:-dev}
REGION="us-east-1"

echo "Adding IAM permissions to AgentCore execution role for $ENVIRONMENT..."

# Get the execution role name
ROLE_NAME="AmazonBedrockAgentCoreSDKRuntime-${REGION}-26d7511235"

# Get Snowflake secret ARN
SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name illuminate-base-$ENVIRONMENT \
  --query 'Stacks[0].Outputs[?OutputKey==`SnowflakeSecretArn`].OutputValue' \
  --output text)

echo "Role: $ROLE_NAME"
echo "Secret ARN: $SECRET_ARN"

# Create policy document
POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "${SECRET_ARN}"
    }
  ]
}
EOF
)

# Create or update inline policy
aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name IlluminateAgentPermissions \
  --policy-document "$POLICY_DOC"

echo "✓ IAM permissions added successfully"
echo ""
echo "Permissions granted:"
echo "  - Bedrock InvokeModel for Claude models"
echo "  - Secrets Manager GetSecretValue for Snowflake credentials"
