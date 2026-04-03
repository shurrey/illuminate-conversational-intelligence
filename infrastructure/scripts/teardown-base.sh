#!/bin/bash
# Tear down the base infrastructure stack (VPC, Cognito, S3, Secrets, WAF).
#
# WARNING: This deletes the Cognito User Pool (all users), VPC, and Secrets.
#
# Usage:
#   ./teardown-base.sh [environment]    # default: dev
set -e

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
STACK_NAME="illuminate-base-${ENVIRONMENT}"

echo "Tearing down base infrastructure ($STACK_NAME)..."

# Empty the artifacts bucket first
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
  --output text --region "$REGION" 2>/dev/null || echo "")

if [ -n "$BUCKET" ] && [ "$BUCKET" != "None" ]; then
  echo "Emptying artifacts bucket: $BUCKET"
  aws s3 rm "s3://$BUCKET" --recursive --quiet
fi

aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
echo "Waiting for stack deletion..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"

# Clean up the IAM role created by agentcore-deploy.sh (not in CloudFormation)
ROLE_NAME="illuminate-agent-role-${ENVIRONMENT}"
if aws iam get-role --role-name "$ROLE_NAME" 2>/dev/null; then
  echo "Cleaning up IAM role: $ROLE_NAME"
  aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name IlluminateAgentPermissions 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_NAME" 2>/dev/null || true
fi

echo "✓ Base infrastructure deleted"
