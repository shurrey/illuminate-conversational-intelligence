#!/bin/bash
# Deploy Illuminate infrastructure (CloudFormation stacks 1-3).
#
# This deploys the AWS infrastructure but NOT the agent code.
# Agent code is deployed separately via agentcore-deploy.sh.
#
# Usage:
#   ./deploy.sh [environment]    # default: dev
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
BASE_STACK="illuminate-base-${ENVIRONMENT}"
AGENTCORE_STACK="illuminate-agentcore-${ENVIRONMENT}"
API_STACK="illuminate-api-${ENVIRONMENT}"

# Work from project root
cd "$(dirname "$0")/../.."
PROJECT_ROOT=$(pwd)

echo -e "${GREEN}Deploying Illuminate infrastructure to ${ENVIRONMENT}${NC}"

# ===========================================
# 1. Deploy base infrastructure (VPC, Cognito, S3, Secrets, WAF)
# ===========================================

echo -e "\n${YELLOW}Deploying base infrastructure...${NC}"
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/1-base-infrastructure.yaml \
  --stack-name "$BASE_STACK" \
  --parameter-overrides Environment="$ENVIRONMENT" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION"
echo -e "${GREEN}✓ Base infrastructure deployed${NC}"

# ===========================================
# 2. Package and upload Lambda handler
# ===========================================

echo -e "\n${YELLOW}Packaging API Lambda handler...${NC}"
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

pip install -q -t "$BUILD_DIR" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  -r requirements-lambda.txt

cp lambda_handler.py "$BUILD_DIR/"
cd "$BUILD_DIR"
zip -q -r "$PROJECT_ROOT/api-handler.zip" . -x "*.pyc" -x "*__pycache__*" -x "*.dist-info/*" -x "*tests/*"
cd "$PROJECT_ROOT"

BUCKET=$(aws cloudformation describe-stacks --stack-name "$BASE_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
  --output text --region "$REGION")

aws s3 cp api-handler.zip "s3://$BUCKET/lambda/api-handler.zip" --quiet
rm -f api-handler.zip
echo -e "${GREEN}✓ Lambda packaged and uploaded${NC}"

# ===========================================
# 3. Deploy API Lambda + Function URL
# ===========================================

echo -e "\n${YELLOW}Looking up Orchestrator ARN from SSM...${NC}"
ORCHESTRATOR_ARN=$(aws ssm get-parameter \
  --name "/illuminate/${ENVIRONMENT}/orchestrator-arn" \
  --query 'Parameter.Value' --output text --region "$REGION" 2>/dev/null || echo "")

if [ -z "$ORCHESTRATOR_ARN" ]; then
  echo -e "${RED}ERROR: Orchestrator ARN not found in SSM. Deploy agents first:${NC}"
  echo -e "${RED}  cd infrastructure && ./agentcore-deploy.sh${NC}"
  exit 1
fi
echo -e "Orchestrator ARN: ${YELLOW}$ORCHESTRATOR_ARN${NC}"

echo -e "\n${YELLOW}Deploying API stack...${NC}"
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/3-api-gateway.yaml \
  --stack-name "$API_STACK" \
  --parameter-overrides \
    Environment="$ENVIRONMENT" \
    BaseStackName="$BASE_STACK" \
    OrchestratorArn="$ORCHESTRATOR_ARN" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION"

API_URL=$(aws cloudformation describe-stacks --stack-name "$API_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' --output text --region "$REGION")

echo -e "${GREEN}✓ API deployed${NC}"

echo -e "\n${GREEN}Infrastructure Deployment Complete!${NC}"
echo -e "Function URL: ${YELLOW}$API_URL${NC}"
echo -e "\nNext steps:"
echo -e "  1. Deploy agents:  cd infrastructure && ./agentcore-deploy.sh"
echo -e "  2. Deploy frontend: ./scripts/deploy-frontend.sh"
