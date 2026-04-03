#!/bin/bash
# Tear down the API stack (Lambda + Function URL).
#
# Usage:
#   ./teardown-api.sh [environment]    # default: dev
set -e

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
STACK_NAME="illuminate-api-${ENVIRONMENT}"

echo "Tearing down API ($STACK_NAME)..."
aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
echo "Waiting for stack deletion..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
echo "✓ API stack deleted"
