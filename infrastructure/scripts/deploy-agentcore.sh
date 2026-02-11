#!/bin/bash
set -e
ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
BASE_STACK="illuminate-base-${ENVIRONMENT}"
AGENTCORE_STACK="illuminate-agentcore-${ENVIRONMENT}"

BUCKET=$(aws cloudformation describe-stacks --stack-name $BASE_STACK \
  --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
  --output text --region $REGION)

echo "Deploying AgentCore to ${ENVIRONMENT}..."
aws cloudformation deploy \
  --template-file cloudformation/2-agentcore.yaml \
  --stack-name $AGENTCORE_STACK \
  --parameter-overrides Environment=$ENVIRONMENT BaseStackName=$BASE_STACK ArtifactsBucket=$BUCKET \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $REGION

echo "✓ AgentCore deployed"
