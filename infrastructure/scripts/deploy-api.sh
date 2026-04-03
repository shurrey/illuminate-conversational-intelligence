#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
STACK_NAME="illuminate-api-${ENVIRONMENT}"
BASE_STACK="illuminate-base-${ENVIRONMENT}"

echo -e "${GREEN}Deploying API Proxy Lambda to ${ENVIRONMENT}${NC}"

# ===========================================
# Package lightweight Lambda
# ===========================================

echo -e "\n${YELLOW}Packaging thin API proxy Lambda...${NC}"

# Work from project root
cd "$(dirname "$0")/../.."
PROJECT_ROOT=$(pwd)

# Create temporary build directory
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Activate virtual environment if present
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
  source "$PROJECT_ROOT/.venv/bin/activate"
fi

# Install Python dependencies into build directory (targeting Lambda's Amazon Linux x86_64)
echo "Installing Lambda dependencies..."
pip install -q -t "$BUILD_DIR" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  -r requirements-lambda.txt

# Copy the Lambda handler and run.sh startup script (NO agents/ directory)
cp lambda_handler.py "$BUILD_DIR/"
cp run.sh "$BUILD_DIR/"

# Create zip from build directory
cd "$BUILD_DIR"
zip -q -r "$PROJECT_ROOT/infrastructure/api-handler.zip" . -x "*.pyc" -x "*__pycache__*" -x "*.dist-info/*" -x "*tests/*"
cd "$PROJECT_ROOT"

PACKAGE_SIZE=$(du -h infrastructure/api-handler.zip | cut -f1)
echo -e "${GREEN}Package size: ${PACKAGE_SIZE} (lightweight - no agent code)${NC}"

# ===========================================
# Upload to S3
# ===========================================

echo -e "\n${YELLOW}Uploading to S3...${NC}"
BUCKET=$(aws cloudformation describe-stacks --stack-name "$BASE_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
  --output text --region "$REGION")

aws s3 cp infrastructure/api-handler.zip "s3://${BUCKET}/lambda/api-handler.zip" --quiet
echo -e "${GREEN}Uploaded to s3://${BUCKET}/lambda/api-handler.zip${NC}"

# ===========================================
# Discover Orchestrator endpoint URL from SSM
# ===========================================

echo -e "\n${YELLOW}Looking up Orchestrator ARN from SSM...${NC}"
ORCHESTRATOR_ARN=$(aws ssm get-parameter \
  --name "/illuminate/${ENVIRONMENT}/orchestrator-arn" \
  --query 'Parameter.Value' --output text --region "$REGION" 2>/dev/null || echo "")

if [ -z "$ORCHESTRATOR_ARN" ]; then
  echo -e "${RED}WARNING: Orchestrator ARN not found in SSM at /illuminate/${ENVIRONMENT}/orchestrator-arn${NC}"
  echo -e "${RED}Run infrastructure/agentcore-deploy.sh first to deploy agents.${NC}"
  echo -e "${YELLOW}Continuing with empty ARN - you can set it manually via CloudFormation parameter override.${NC}"
fi

echo -e "Orchestrator ARN: ${ORCHESTRATOR_ARN:-'(not set)'}"

# ===========================================
# Deploy CloudFormation stack
# ===========================================

echo -e "\n${YELLOW}Deploying API Gateway stack...${NC}"
if [ -z "$ORCHESTRATOR_ARN" ]; then
  echo -e "${RED}ERROR: Orchestrator ARN not found. Cannot deploy API without it.${NC}"
  echo -e "${RED}Run 'agentcore deploy' for the orchestrator first, then store the ARN:${NC}"
  echo -e "${RED}  aws ssm put-parameter --name /illuminate/$ENVIRONMENT/orchestrator-arn --value <ARN> --type String --overwrite${NC}"
  exit 1
fi

# Look up CloudFront origin if frontend stack exists
FRONTEND_STACK="illuminate-frontend-${ENVIRONMENT}"
FRONTEND_ORIGIN=$(aws cloudformation describe-stacks --stack-name "$FRONTEND_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontURL`].OutputValue' \
  --output text --region "$REGION" 2>/dev/null || echo "")

PARAM_OVERRIDES="Environment=$ENVIRONMENT BaseStackName=$BASE_STACK OrchestratorArn=$ORCHESTRATOR_ARN"
if [ -n "$FRONTEND_ORIGIN" ]; then
  PARAM_OVERRIDES="$PARAM_OVERRIDES FrontendOrigin=$FRONTEND_ORIGIN"
  echo -e "Frontend origin: ${YELLOW}$FRONTEND_ORIGIN${NC}"
fi

aws cloudformation deploy \
  --template-file infrastructure/cloudformation/3-api-gateway.yaml \
  --stack-name "$STACK_NAME" \
  --parameter-overrides $PARAM_OVERRIDES \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --region "$REGION"

# ===========================================
# Output results
# ===========================================

API_URL=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text --region "$REGION")

# Cleanup
rm -f infrastructure/api-handler.zip

echo -e "\n${GREEN}API Proxy Lambda Deployment Complete!${NC}"
echo -e "Function URL: ${YELLOW}${API_URL}${NC}"
echo -e "\nThe Lambda proxy forwards all requests to AgentCore Orchestrator via A2A protocol."
echo -e "No agent code runs in the Lambda — all agent logic runs in AgentCore runtimes.\n"
