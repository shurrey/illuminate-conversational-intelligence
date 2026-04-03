#!/bin/bash
# Deploy the Illuminate frontend (build, S3 upload, CloudFront invalidation).
#
# Usage:
#   ./deploy-frontend.sh [environment]    # default: dev
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
BASE_STACK="illuminate-base-${ENVIRONMENT}"
API_STACK="illuminate-api-${ENVIRONMENT}"
FRONTEND_STACK="illuminate-frontend-${ENVIRONMENT}"

# Work from project root
cd "$(dirname "$0")/../.."
PROJECT_ROOT=$(pwd)

echo -e "${GREEN}Deploying Frontend to ${ENVIRONMENT}${NC}"

# ===========================================
# Get backend configuration from CloudFormation
# ===========================================

echo -e "\n${YELLOW}Getting backend configuration...${NC}"
API_URL=$(aws cloudformation describe-stacks --stack-name "$API_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' --output text --region "$REGION")

USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name "$BASE_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text --region "$REGION")

USER_POOL_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name "$BASE_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text --region "$REGION")

echo "Function URL: $API_URL"
echo "User Pool ID: $USER_POOL_ID"

# ===========================================
# Deploy CloudFront stack
# ===========================================

echo -e "\n${YELLOW}Deploying CloudFront and S3...${NC}"
aws cloudformation deploy \
  --template-file "$PROJECT_ROOT/infrastructure/cloudformation/4-frontend.yaml" \
  --stack-name "$FRONTEND_STACK" \
  --parameter-overrides \
    Environment="$ENVIRONMENT" \
    BaseStackName="$BASE_STACK" \
    ApiStackName="$API_STACK" \
  --no-fail-on-empty-changeset \
  --region "$REGION"

BUCKET=$(aws cloudformation describe-stacks --stack-name "$FRONTEND_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendBucketName`].OutputValue' --output text --region "$REGION")

CLOUDFRONT_URL=$(aws cloudformation describe-stacks --stack-name "$FRONTEND_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontURL`].OutputValue' --output text --region "$REGION")

CLOUDFRONT_ID=$(aws cloudformation describe-stacks --stack-name "$FRONTEND_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDistributionId`].OutputValue' --output text --region "$REGION")

echo -e "${GREEN}✓ CloudFront deployed${NC}"

# ===========================================
# Build frontend
# ===========================================

echo -e "\n${YELLOW}Building frontend...${NC}"
cd "$PROJECT_ROOT/frontend"

# Generate build-time env (VITE_ vars only, from CF outputs)
# API calls go directly to Function URL (bypasses CloudFront 60s timeout)
cat > .env.production.local << EOF
VITE_API_URL=${API_URL%/}
VITE_USER_POOL_ID=$USER_POOL_ID
VITE_USER_POOL_CLIENT_ID=$USER_POOL_CLIENT_ID
EOF

npm install --silent
npm run build

# Cleanup build-time env
rm -f .env.production.local

echo -e "${GREEN}✓ Frontend built${NC}"

# ===========================================
# Upload to S3
# ===========================================

echo -e "\n${YELLOW}Uploading to S3...${NC}"
aws s3 sync dist/ "s3://$BUCKET/" --delete --quiet

echo -e "${GREEN}✓ Uploaded to S3${NC}"

# ===========================================
# Invalidate CloudFront cache
# ===========================================

echo -e "\n${YELLOW}Invalidating CloudFront cache...${NC}"
aws cloudfront create-invalidation \
  --distribution-id "$CLOUDFRONT_ID" \
  --paths "/*" \
  --query 'Invalidation.Id' \
  --output text

echo -e "${GREEN}✓ Cache invalidated${NC}"

# ===========================================
# Ensure API Lambda allows this CloudFront origin (CORS)
# ===========================================

echo -e "\n${YELLOW}Updating API Lambda CORS origins...${NC}"
LAMBDA_NAME=$(aws cloudformation describe-stacks --stack-name "$API_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`FunctionName`].OutputValue' \
  --output text --region "$REGION" 2>/dev/null || echo "")

if [ -z "$LAMBDA_NAME" ] || [ "$LAMBDA_NAME" = "None" ]; then
  # Fall back to convention-based name
  LAMBDA_NAME="illuminate-api-${ENVIRONMENT}"
fi

CURRENT_ORIGINS=$(aws lambda get-function-configuration \
  --function-name "$LAMBDA_NAME" --region "$REGION" \
  --query 'Environment.Variables.ALLOWED_ORIGINS' --output text 2>/dev/null || echo "")

if [ -n "$CURRENT_ORIGINS" ] && ! echo "$CURRENT_ORIGINS" | grep -q "$CLOUDFRONT_URL"; then
  # Read all current env vars, add the CloudFront origin
  ENV_JSON=$(aws lambda get-function-configuration \
    --function-name "$LAMBDA_NAME" --region "$REGION" \
    --query 'Environment.Variables' 2>/dev/null)
  UPDATED_JSON=$(echo "$ENV_JSON" | python3 -c "
import sys, json
env = json.load(sys.stdin)
origins = env.get('ALLOWED_ORIGINS', '')
env['ALLOWED_ORIGINS'] = origins + ',$CLOUDFRONT_URL'
print(json.dumps({'Variables': env}))
")
  aws lambda update-function-configuration \
    --function-name "$LAMBDA_NAME" --region "$REGION" \
    --environment "$UPDATED_JSON" > /dev/null
  echo -e "${GREEN}✓ Added $CLOUDFRONT_URL to ALLOWED_ORIGINS${NC}"
else
  echo -e "${GREEN}✓ CORS origins already up to date${NC}"
fi

# ===========================================
# Output
# ===========================================

echo -e "\n${GREEN}Frontend Deployment Complete!${NC}"
echo -e "CloudFront URL: ${YELLOW}$CLOUDFRONT_URL${NC}"
echo -e "Function URL:   ${YELLOW}$API_URL${NC}"
echo ""
