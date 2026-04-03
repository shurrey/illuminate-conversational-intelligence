#!/bin/bash
# Tear down the frontend stack (S3 + CloudFront).
#
# Usage:
#   ./teardown-frontend.sh [environment]    # default: dev
set -e

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
STACK_NAME="illuminate-frontend-${ENVIRONMENT}"

echo "Tearing down frontend ($STACK_NAME)..."

# Empty the S3 bucket first (CloudFormation can't delete non-empty buckets)
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendBucketName`].OutputValue' \
  --output text --region "$REGION" 2>/dev/null || echo "")

if [ -n "$BUCKET" ] && [ "$BUCKET" != "None" ]; then
  echo "Emptying S3 bucket: $BUCKET"
  aws s3 rm "s3://$BUCKET" --recursive --quiet
fi

aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
echo "Waiting for stack deletion..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
echo "✓ Frontend stack deleted"
