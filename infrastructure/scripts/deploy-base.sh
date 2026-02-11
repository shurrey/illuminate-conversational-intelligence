#!/bin/bash
# Deploy base infrastructure (VPC, Cognito, S3, Secrets Manager, WAF).
#
# Snowflake credentials must be passed as environment variables or
# already exist in Secrets Manager from a prior deployment.
#
# Usage:
#   ./deploy-base.sh [environment]    # default: dev
#
# Environment variables (for initial deployment):
#   SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
#   SNOWFLAKE_DATABASE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_ROLE
set -e

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
STACK_NAME="illuminate-base-$ENVIRONMENT"

echo "Deploying base infrastructure to $ENVIRONMENT..."

aws cloudformation deploy \
  --template-file "$(dirname "$0")/../cloudformation/1-base-infrastructure.yaml" \
  --stack-name "$STACK_NAME" \
  --parameter-overrides \
    Environment="$ENVIRONMENT" \
    SnowflakeAccount="${SNOWFLAKE_ACCOUNT:-}" \
    SnowflakeUser="${SNOWFLAKE_USER:-}" \
    SnowflakePassword="${SNOWFLAKE_PASSWORD:-}" \
    SnowflakeDatabase="${SNOWFLAKE_DATABASE:-}" \
    SnowflakeWarehouse="${SNOWFLAKE_WAREHOUSE:-}" \
    SnowflakeRole="${SNOWFLAKE_ROLE:-}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION"

echo "✓ Base infrastructure deployed"
