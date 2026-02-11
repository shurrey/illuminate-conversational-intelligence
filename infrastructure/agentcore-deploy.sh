#!/bin/bash
set -e

ENVIRONMENT=${1:-dev}
echo "Deploying AgentCore agents to $ENVIRONMENT"

# Activate venv
cd ..
source venv/bin/activate
cd infrastructure

# Get Cognito configuration from base stack
USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name illuminate-base-$ENVIRONMENT \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text)

CLIENT_ID=$(aws cloudformation describe-stacks \
  --stack-name illuminate-base-$ENVIRONMENT \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text)

ISSUER_URL="https://cognito-idp.us-east-1.amazonaws.com/$USER_POOL_ID"

echo "Using Cognito User Pool: $USER_POOL_ID"
echo "Using Client ID: $CLIENT_ID"

# Get Snowflake secret ARN
SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name illuminate-base-$ENVIRONMENT \
  --query 'Stacks[0].Outputs[?OutputKey==`SnowflakeSecretArn`].OutputValue' \
  --output text)

echo "Snowflake Secret ARN: $SECRET_ARN"

# Create IAM role with proper permissions
echo "Creating IAM execution role with Bedrock and Secrets Manager permissions..."
ROLE_NAME="illuminate-agent-role-$ENVIRONMENT"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create trust policy
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)

# Create permissions policy
PERMISSIONS_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "$SECRET_ARN"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:$ACCOUNT_ID:log-group:/aws/bedrock-agentcore/*"
    }
  ]
}
EOF
)

# Create role if it doesn't exist
if aws iam get-role --role-name $ROLE_NAME 2>/dev/null; then
  echo "Role $ROLE_NAME already exists, updating trust policy and permissions..."
  aws iam update-assume-role-policy \
    --role-name $ROLE_NAME \
    --policy-document "$TRUST_POLICY"
else
  echo "Creating role $ROLE_NAME..."
  aws iam create-role \
    --role-name $ROLE_NAME \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Execution role for Illuminate AgentCore agents"
fi

# Attach/update inline policy
aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name IlluminateAgentPermissions \
  --policy-document "$PERMISSIONS_POLICY"

# Wait for IAM role to propagate
echo "Waiting 10 seconds for IAM role to propagate..."
sleep 10

ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"
echo "✓ IAM role ready: $ROLE_ARN"
echo ""

# Create OAuth authorizer config JSON
AUTH_CONFIG=$(cat <<EOF
{
  "customJWTAuthorizer": {
    "discoveryUrl": "$ISSUER_URL/.well-known/openid-configuration",
    "allowedAudience": ["$CLIENT_ID"],
    "allowedClients": ["$CLIENT_ID"]
  }
}
EOF
)

# Deploy SQL Agent
echo "Deploying SQL Agent..."
cd ../agents/sql
agentcore configure -e a2a_server.py --protocol A2A --non-interactive \
  --authorizer-config "$AUTH_CONFIG" --name "illuminate_sql_$ENVIRONMENT" \
  --execution-role "$ROLE_ARN"
SQL_ARN=$(agentcore launch 2>&1 | tee /dev/tty | grep -o 'arn:aws:bedrock-agentcore:[^ ]*' | head -1 || echo "")
if [ -z "$SQL_ARN" ]; then
  echo "Failed to get SQL ARN"
  exit 1
fi
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/sql-arn" --value "$SQL_ARN" --type String --overwrite
echo "✓ SQL agent deployed: $SQL_ARN"
echo ""

# Deploy Analyst Agent
echo "Deploying Analyst Agent..."
cd ../analyst
agentcore configure -e a2a_server.py --protocol A2A --non-interactive \
  --authorizer-config "$AUTH_CONFIG" --name "illuminate_analyst_$ENVIRONMENT" \
  --execution-role "$ROLE_ARN"
ANALYST_ARN=$(agentcore launch 2>&1 | tee /dev/tty | grep -o 'arn:aws:bedrock-agentcore:[^ ]*' | head -1 || echo "")
if [ -z "$ANALYST_ARN" ]; then
  echo "Failed to get Analyst ARN"
  exit 1
fi
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/analyst-arn" --value "$ANALYST_ARN" --type String --overwrite
echo "✓ Analyst agent deployed: $ANALYST_ARN"
echo ""

# Deploy Writer Agent
echo "Deploying Writer Agent..."
cd ../writer
agentcore configure -e a2a_server.py --protocol A2A --non-interactive \
  --authorizer-config "$AUTH_CONFIG" --name "illuminate_writer_$ENVIRONMENT" \
  --execution-role "$ROLE_ARN"
WRITER_ARN=$(agentcore launch 2>&1 | tee /dev/tty | grep -o 'arn:aws:bedrock-agentcore:[^ ]*' | head -1 || echo "")
if [ -z "$WRITER_ARN" ]; then
  echo "Failed to get Writer ARN"
  exit 1
fi
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/writer-arn" --value "$WRITER_ARN" --type String --overwrite
echo "✓ Writer agent deployed: $WRITER_ARN"
echo ""

# Deploy Validator Agent
echo "Deploying Validator Agent..."
cd ../validator
agentcore configure -e a2a_server.py --protocol A2A --non-interactive \
  --authorizer-config "$AUTH_CONFIG" --name "illuminate_validator_$ENVIRONMENT" \
  --execution-role "$ROLE_ARN"
VALIDATOR_ARN=$(agentcore launch 2>&1 | tee /dev/tty | grep -o 'arn:aws:bedrock-agentcore:[^ ]*' | head -1 || echo "")
if [ -z "$VALIDATOR_ARN" ]; then
  echo "Failed to get Validator ARN"
  exit 1
fi
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/validator-arn" --value "$VALIDATOR_ARN" --type String --overwrite
echo "✓ Validator agent deployed: $VALIDATOR_ARN"
echo ""

# Get runtime URLs for each agent
SQL_URL="https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/$(echo $SQL_ARN | sed 's|arn:aws:bedrock-agentcore:us-east-1:[0-9]*:runtime/||')/invocations/"
ANALYST_URL="https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/$(echo $ANALYST_ARN | sed 's|arn:aws:bedrock-agentcore:us-east-1:[0-9]*:runtime/||')/invocations/"
WRITER_URL="https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/$(echo $WRITER_ARN | sed 's|arn:aws:bedrock-agentcore:us-east-1:[0-9]*:runtime/||')/invocations/"
VALIDATOR_URL="https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/$(echo $VALIDATOR_ARN | sed 's|arn:aws:bedrock-agentcore:us-east-1:[0-9]*:runtime/||')/invocations/"

# Store URLs in SSM
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/sql-url" --value "$SQL_URL" --type String --overwrite
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/analyst-url" --value "$ANALYST_URL" --type String --overwrite
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/writer-url" --value "$WRITER_URL" --type String --overwrite
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/validator-url" --value "$VALIDATOR_URL" --type String --overwrite

echo "✓ Agent URLs stored in SSM Parameter Store"
echo ""

# Deploy Orchestrator Agent LAST with all agent URLs
echo "Deploying Orchestrator Agent with specialist agent URLs..."
cd ../orchestrator

# Create .env file with agent URLs for orchestrator
cat > .env.agentcore << EOF
ILLUMINATE_USE_A2A=true
SQL_AGENT_URL=$SQL_URL
ANALYST_AGENT_URL=$ANALYST_URL
WRITER_AGENT_URL=$WRITER_URL
VALIDATOR_AGENT_URL=$VALIDATOR_URL
EOF

agentcore configure -e a2a_server.py --protocol A2A --non-interactive \
  --authorizer-config "$AUTH_CONFIG" --name "illuminate_orchestrator_$ENVIRONMENT" \
  --execution-role "$ROLE_ARN"
ORCHESTRATOR_ARN=$(agentcore launch 2>&1 | tee /dev/tty | grep -o 'arn:aws:bedrock-agentcore:[^ ]*' | head -1 || echo "")
if [ -z "$ORCHESTRATOR_ARN" ]; then
  echo "Failed to get Orchestrator ARN"
  exit 1
fi
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/orchestrator-arn" --value "$ORCHESTRATOR_ARN" --type String --overwrite

# Store orchestrator URL in SSM (used by Lambda API proxy)
ORCHESTRATOR_URL="https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/$(echo $ORCHESTRATOR_ARN | sed 's|arn:aws:bedrock-agentcore:us-east-1:[0-9]*:runtime/||')/invocations/"
aws ssm put-parameter --name "/illuminate/$ENVIRONMENT/orchestrator-url" --value "$ORCHESTRATOR_URL" --type String --overwrite

echo "✓ Orchestrator agent deployed: $ORCHESTRATOR_ARN"
echo "  URL: $ORCHESTRATOR_URL"
echo ""

echo "✓ All agents deployed successfully"
echo ""
echo "Agent ARNs:"
echo "  Orchestrator: $ORCHESTRATOR_ARN"
echo "  SQL: $SQL_ARN"
echo "  Analyst: $ANALYST_ARN"
echo "  Writer: $WRITER_ARN"
echo "  Validator: $VALIDATOR_ARN"
echo ""
echo "Agent URLs:"
echo "  Orchestrator: $ORCHESTRATOR_URL"
echo "  SQL: $SQL_URL"
echo "  Analyst: $ANALYST_URL"
echo "  Writer: $WRITER_URL"
echo "  Validator: $VALIDATOR_URL"
