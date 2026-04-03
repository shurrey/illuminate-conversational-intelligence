#!/bin/bash
# Deploy base infrastructure (VPC, Cognito, S3, Secrets Manager, WAF).
#
# Snowflake credentials are loaded from the .env file at the project root
# (falls back to shell environment variables). They must be available for
# the initial deployment; after that the secret persists in Secrets Manager.
#
# Usage:
#   ./deploy-base.sh [environment]    # default: dev
#
# Setup:
#   cp .env.example .env   # then fill in your values
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load .env file if it exists (does not override existing env vars)
if [ -f "$PROJECT_ROOT/.env" ]; then
  echo "Loading environment from $PROJECT_ROOT/.env"
  ENV_TMP=$(mktemp)
  "$PROJECT_ROOT/.venv/bin/python3" -c "
from dotenv import dotenv_values
for k, v in dotenv_values('$PROJECT_ROOT/.env').items():
    v_escaped = v.replace(\"'\", \"'\\\"'\\\"'\")
    print(f\"{k}='{v_escaped}'\")
" > "$ENV_TMP"
  set -a
  source "$ENV_TMP"
  set +a
  rm -f "$ENV_TMP"
fi

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

# ===========================================
# Create initial Cognito user (if credentials provided)
# ===========================================

if [ -n "${COGNITO_USER_EMAIL:-}" ] && [ -n "${COGNITO_USER_PASSWORD:-}" ]; then
  USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
    --output text --region "$REGION")
  CLIENT_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
    --output text --region "$REGION")

  echo "Creating Cognito user: $COGNITO_USER_EMAIL"

  # Sign up (may fail if user already exists — that's OK)
  aws cognito-idp sign-up \
    --client-id "$CLIENT_ID" \
    --username "$COGNITO_USER_EMAIL" \
    --password "$COGNITO_USER_PASSWORD" \
    --user-attributes Name=email,Value="$COGNITO_USER_EMAIL" Name=name,Value="${COGNITO_USER_NAME:-Admin}" \
    --region "$REGION" 2>/dev/null && \
  aws cognito-idp admin-confirm-sign-up \
    --user-pool-id "$USER_POOL_ID" \
    --username "$COGNITO_USER_EMAIL" \
    --region "$REGION" && \
  aws cognito-idp admin-update-user-attributes \
    --user-pool-id "$USER_POOL_ID" \
    --username "$COGNITO_USER_EMAIL" \
    --user-attributes Name=email_verified,Value=true \
    --region "$REGION" && \
  echo "✓ Cognito user created and confirmed" || \
  echo "⚠ Cognito user may already exist (skipping)"
fi
