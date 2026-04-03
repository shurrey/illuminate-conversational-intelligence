# Illuminate Conversational Intelligence - Deployment Guide

This document describes how to deploy the Illuminate ICI platform from scratch
and how to update individual components after the initial deployment.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Initial Setup (Snowflake Credentials)](#2-initial-setup-snowflake-credentials)
3. [Infrastructure Deployment](#3-infrastructure-deployment)
4. [Agent Deployment](#4-agent-deployment)
5. [Frontend Deployment](#5-frontend-deployment)
6. [Cognito User Setup](#6-cognito-user-setup)
7. [Verification](#7-verification)
8. [Updating Individual Components](#8-updating-individual-components)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### Required Tools

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI v2 | Latest | Infrastructure provisioning and S3 uploads |
| Python | 3.11+ | Agent code, Lambda packaging, virtual environment |
| Node.js | 18+ | Frontend build (React + Vite) |
| npm | Bundled with Node.js | Frontend dependency management |
| Bedrock AgentCore CLI | Latest | Deploying agent runtimes to Bedrock AgentCore |

### AWS Permissions

The deploying IAM principal needs permissions for:

- CloudFormation (create/update stacks)
- IAM (create roles, attach policies)
- S3 (create buckets, upload objects)
- Lambda (create/update functions)
- CloudFront (create distributions, invalidate cache)
- Cognito (create user pools)
- Secrets Manager (create/read secrets)
- WAF v2 (create web ACLs -- both REGIONAL and CLOUDFRONT scopes)
- SSM Parameter Store (put/get parameters)
- Bedrock (model access)
- Bedrock AgentCore (deploy/invoke runtimes)

### Bedrock Model Access

Before deploying, enable access to the following models in the **us-east-1**
region via the Bedrock console (Model Access page):

- **Claude Sonnet 4.6** (`anthropic.claude-sonnet-4-6`)
- **Claude Opus 4.6** (`anthropic.claude-opus-4-6-v1`)

### Snowflake Account

You need a Snowflake account with:

- Account identifier
- Service user credentials (username + password)
- Database name
- Warehouse name
- Role with read access to the relevant schemas

### Region

All resources deploy to **us-east-1** by default. Override with the
`AWS_REGION` environment variable if needed (note: Bedrock AgentCore
availability may vary by region).

---

## 2. Initial Setup (Snowflake Credentials)

Snowflake credentials are passed to the base infrastructure stack and stored
in AWS Secrets Manager. Create a `.env` file from the provided example:

```bash
cp .env.example .env
```

Then edit `.env` and fill in your values:

```
SNOWFLAKE_ACCOUNT=your-account-identifier
SNOWFLAKE_USER=SVC_BLACKBOARD_DATA
SNOWFLAKE_PASSWORD=your-password
SNOWFLAKE_DATABASE=your-database
SNOWFLAKE_WAREHOUSE=BLACKBOARD_DATA_WH
SNOWFLAKE_ROLE=BBDATA_USER_ROLE
```

The `.env` file is loaded automatically by `deploy-base.sh`. Values are passed
as `NoEcho` parameters to CloudFormation and stored in the Secrets Manager
secret `illuminate/dev/snowflake`. After the initial deployment, the secret
persists in Secrets Manager and does not need to be re-supplied for subsequent
stack updates.

> **Note:** `.env` is gitignored and should never be committed.

### Python Virtual Environment

Create a virtual environment at the project root:

```bash
cd /path/to/illuminate
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install python-dotenv
```

---

## 3. Infrastructure Deployment

Infrastructure is managed via four CloudFormation stacks deployed in order.
All templates live in `infrastructure/cloudformation/`.

### Deployment Order

The stacks must be deployed in this sequence because later stacks reference
outputs from earlier ones:

```
1-base-infrastructure.yaml
        |
        v
2-agentcore.yaml
        |
        v
3-api-gateway.yaml  (requires agent URLs in SSM -- see Step 4)
        |
        v
4-frontend.yaml
```

### Stack Details

| Stack | Template | Resources |
|-------|----------|-----------|
| `illuminate-base-{env}` | `1-base-infrastructure.yaml` | VPC, subnets, Cognito User Pool + App Client, S3 artifacts bucket, Secrets Manager (Snowflake), REGIONAL WAF |
| `illuminate-agentcore-{env}` | `2-agentcore.yaml` | AgentCore Gateway, Memory configuration, agent runtime definitions |
| `illuminate-api-{env}` | `3-api-gateway.yaml` | Lambda proxy function, Lambda Function URL (AuthType: NONE), IAM permissions for Function URL invocation |
| `illuminate-frontend-{env}` | `4-frontend.yaml` | S3 bucket (private, OAC), CloudFront distribution, GLOBAL WAF, SPA error routing (403/404 -> /index.html) |

### Option A: Deploy Stacks 1-3 with the Main Script

The main deploy script (`infrastructure/scripts/deploy.sh`) deploys stacks
1 through 3 in one run. It also packages the Lambda and uploads it to S3.

**Important:** Stack 3 requires the orchestrator URL in SSM. Deploy agents
first (Step 4) or deploy only the base stack first, then agents, then
run the full script.

```bash
# From project root
infrastructure/scripts/deploy.sh dev
```

This script:
1. Deploys `1-base-infrastructure.yaml`
2. Packages `lambda_handler.py` with dependencies into a zip
   - Uses `pip install --platform manylinux2014_x86_64 --python-version 3.11`
   - Dependencies from `requirements-lambda.txt`: fastapi, pydantic, mangum, python-jose, requests
   - boto3 is NOT included (provided by the Lambda runtime)
3. Uploads the zip to the artifacts S3 bucket
4. Reads the orchestrator URL from SSM (`/illuminate/{env}/orchestrator-url`)
5. Deploys `3-api-gateway.yaml`

### Option B: Deploy Stacks Individually

```bash
# Stack 1: Base infrastructure (reads credentials from .env)
infrastructure/scripts/deploy-base.sh dev

# Stack 2: AgentCore CloudFormation resources
infrastructure/scripts/deploy-agentcore.sh dev

# (Deploy agents here -- see Step 4)

# Stack 3: API Lambda + Function URL
infrastructure/scripts/deploy-api.sh dev
```

### Recommended First-Time Order

For a clean first-time deployment:

```
1. deploy-base.sh dev          # Stack 1
2. deploy-agentcore.sh dev     # Stack 2
3. agentcore-deploy.sh dev     # Agent code (Step 4) -- stores URLs in SSM
4. deploy-api.sh dev           # Stack 3 -- reads orchestrator URL from SSM
5. deploy-frontend.sh dev      # Stack 4 + build + upload (Step 5)
```

---

## 4. Agent Deployment

Agent code is deployed to Bedrock AgentCore using the `agentcore` CLI, **not**
CloudFormation. The deployment script is `infrastructure/agentcore-deploy.sh`.

### Architecture

Five agents run as independent AgentCore runtimes:

| Agent | Name Pattern | Purpose |
|-------|-------------|---------|
| SQL | `illuminate_sql_{env}` | Generates and executes Snowflake SQL queries |
| Analyst | `illuminate_analyst_{env}` | Statistical analysis and interpretation |
| Writer | `illuminate_writer_{env}` | Natural language report generation |
| Validator | `illuminate_validator_{env}` | Query and result validation |
| Orchestrator | `illuminate_orchestrator_{env}` | Coordinates all specialist agents (deployed last) |

Each agent is a self-contained `a2a_server.py` file with zero cross-imports
from `agents/`. The AgentCore deploy process (`agentcore launch`) flattens all
source files to the zip root.

### Running the Agent Deploy

```bash
cd infrastructure
./agentcore-deploy.sh dev
```

The script performs the following for each agent:

1. Reads Cognito configuration from the base stack outputs
2. Creates/updates the IAM execution role (`illuminate-agent-role-{env}`) with:
   - `bedrock:InvokeModel` for Claude models
   - `secretsmanager:GetSecretValue` for the Snowflake secret
   - `logs:CreateLogGroup/CreateLogStream/PutLogEvents`
3. Configures OAuth JWT authorizer (Cognito OIDC discovery)
4. Runs `agentcore configure` + `agentcore launch` for each agent
5. Stores the runtime ARN and URL in SSM Parameter Store:
   - `/illuminate/{env}/sql-arn`, `/illuminate/{env}/sql-url`
   - `/illuminate/{env}/analyst-arn`, `/illuminate/{env}/analyst-url`
   - `/illuminate/{env}/writer-arn`, `/illuminate/{env}/writer-url`
   - `/illuminate/{env}/validator-arn`, `/illuminate/{env}/validator-url`
   - `/illuminate/{env}/orchestrator-arn`, `/illuminate/{env}/orchestrator-url`
6. The Orchestrator is deployed **last** because it needs the URLs of all
   specialist agents (written to `.env.agentcore` in the orchestrator directory)

### Granting Additional Permissions

If the AgentCore-managed execution role needs extra permissions (e.g., after
the role name changes), use:

```bash
infrastructure/scripts/grant-agent-permissions.sh dev
```

---

## 5. Frontend Deployment

The frontend is a React 18 + TypeScript application built with Vite and styled
with TailwindCSS. It authenticates users via Cognito
(`amazon-cognito-identity-js`).

### Deploy Command

```bash
infrastructure/scripts/deploy-frontend.sh dev
```

The script:

1. Reads backend configuration from CloudFormation stack outputs:
   - Function URL from the API stack
   - Cognito User Pool ID and Client ID from the base stack
2. Deploys `4-frontend.yaml` (S3 bucket + CloudFront + GLOBAL WAF)
3. Writes `.env.production.local` with the `VITE_` variables:
   ```
   VITE_API_URL=<function-url>
   VITE_USER_POOL_ID=<pool-id>
   VITE_USER_POOL_CLIENT_ID=<client-id>
   ```
4. Runs `npm install` and `npm run build` in the `frontend/` directory
5. Syncs `frontend/dist/` to the S3 bucket
6. Invalidates the CloudFront cache (`/*`)
7. Cleans up `.env.production.local`

### CloudFront Routing

CloudFront is configured with two origins:

| Path Pattern | Origin | Purpose |
|-------------|--------|---------|
| `/api/*`, `/health` | Lambda Function URL | API requests proxied to Lambda |
| `/*` (default) | S3 bucket (via OAC) | Frontend static assets |

SPA routing is handled by CloudFront custom error responses: both 403 and 404
errors from S3 are rewritten to serve `/index.html` with a 200 status code.

---

## 6. Cognito User Setup

### Creating Users

Use the Cognito `sign_up` flow rather than `admin-create-user`. The
admin-create-user path has known issues with the FORCE_CHANGE_PASSWORD state
that can block authentication.

```python
import boto3

client = boto3.client('cognito-idp', region_name='us-east-1')

# Sign up
client.sign_up(
    ClientId='<USER_POOL_CLIENT_ID>',
    Username='user@example.com',
    Password='YourSecurePassword123!',
    UserAttributes=[
        {'Name': 'email', 'Value': 'user@example.com'},
        {'Name': 'name', 'Value': 'Demo User'},
    ]
)

# Confirm the user (admin confirmation, no email verification needed)
client.admin_confirm_sign_up(
    UserPoolId='<USER_POOL_ID>',
    Username='user@example.com'
)
```

### Getting the Cognito IDs

```bash
# User Pool ID
aws cloudformation describe-stacks \
  --stack-name illuminate-base-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text

# Client ID
aws cloudformation describe-stacks \
  --stack-name illuminate-base-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text
```

---

## 7. Verification

### Health Check

After deploying the API stack, verify the Lambda is reachable:

```bash
# Get the Function URL
API_URL=$(aws cloudformation describe-stacks \
  --stack-name illuminate-api-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text)

curl -s "$API_URL/health" | python3 -m json.tool
```

Expected response:

```json
{
    "status": "healthy",
    "version": "0.2.0",
    "mode": "proxy"
}
```

### Frontend

After deploying the frontend, get the CloudFront URL:

```bash
aws cloudformation describe-stacks \
  --stack-name illuminate-frontend-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontURL`].OutputValue' \
  --output text
```

Open `https://<cloudfront-domain>` in a browser. You should see the login page.

### Agent Health

Check that agents are running via AgentCore:

```bash
agentcore list
```

All five agents should show as ACTIVE:

- `illuminate_sql_dev`
- `illuminate_analyst_dev`
- `illuminate_writer_dev`
- `illuminate_validator_dev`
- `illuminate_orchestrator_dev`

### End-to-End Test

1. Open the CloudFront URL in a browser
2. Log in with a Cognito user (see Step 6)
3. Send a test message like "What tables are available?"
4. Verify you receive a response from the orchestrator

---

## 8. Updating Individual Components

### Update Agent Code Only

Re-run the agent deploy script. This rebuilds and re-launches all agents:

```bash
cd infrastructure
./agentcore-deploy.sh dev
```

To redeploy a single agent manually:

```bash
cd agents/sql
agentcore configure -e a2a_server.py --protocol A2A --non-interactive \
  --name "illuminate_sql_dev"
agentcore launch
```

### Update Lambda Code Only

Re-package and redeploy the API Lambda without touching other stacks:

```bash
infrastructure/scripts/deploy-api.sh dev
```

### Update Frontend Only

Rebuild and redeploy the frontend without touching infrastructure:

```bash
infrastructure/scripts/deploy-frontend.sh dev
```

This builds the React app, syncs to S3, and invalidates CloudFront.

### Update Base Infrastructure

Modify `1-base-infrastructure.yaml` and run:

```bash
infrastructure/scripts/deploy-base.sh dev
```

### Update AgentCore CloudFormation Resources

Modify `2-agentcore.yaml` and run:

```bash
infrastructure/scripts/deploy-agentcore.sh dev
```

### Full Redeploy

Run all steps in sequence:

```bash
# Stacks 1-2
infrastructure/scripts/deploy-base.sh dev
infrastructure/scripts/deploy-agentcore.sh dev

# Agent code
cd infrastructure && ./agentcore-deploy.sh dev && cd ..

# Stack 3 (reads orchestrator URL from SSM)
infrastructure/scripts/deploy-api.sh dev

# Stack 4 + frontend build
infrastructure/scripts/deploy-frontend.sh dev
```

---

## 9. Troubleshooting

### Common Errors

#### `424` from AgentCore

**Cause:** The agent container never started.

**Fix:**
- Check the agent's `a2a_server.py` for import errors. All imports must be
  self-contained (no `from agents.*` imports).
- Verify the execution role exists and has the correct trust policy for
  `bedrock-agentcore.amazonaws.com`.
- Check CloudWatch logs at `/aws/bedrock-agentcore/illuminate_<agent>_<env>`.

#### `502` from AgentCore

**Cause:** The container started but the application is not responding.

**Fix:**
- Check that `a2a_server.py` binds to the correct port.
- Look for runtime exceptions in CloudWatch logs.
- Ensure all Python dependencies are listed in the agent's `requirements.txt`.

#### "Init time exceeded" from AgentCore

**Cause:** Agent startup takes too long (heavy imports, slow initialization).

**Fix:**
- Minimize imports at module level.
- Defer heavy initialization (model loading, database connections) to first
  request rather than module load time.

#### Orchestrator URL Not Found in SSM

**Error:** `ERROR: Orchestrator URL not found in SSM`

**Cause:** The API deploy script (`deploy-api.sh` or `deploy.sh`) reads
`/illuminate/{env}/orchestrator-url` from SSM. This is written by
`agentcore-deploy.sh`.

**Fix:** Deploy agents first:
```bash
cd infrastructure && ./agentcore-deploy.sh dev
```

Or manually set the parameter:
```bash
aws ssm put-parameter \
  --name /illuminate/dev/orchestrator-url \
  --value "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/<runtime-id>/invocations/" \
  --type String --overwrite
```

#### Lambda Function URL Returns 403

**Cause:** Missing invocation permissions. Lambda Function URLs with
`AuthType: NONE` require **two** permissions:
1. `lambda:InvokeFunctionUrl` (standard)
2. `lambda:InvokeFunction` with condition `lambda:InvokedViaFunctionUrl: true`

**Fix:** Verify both permissions exist in the CloudFormation template
(`3-api-gateway.yaml`). If deploying manually via boto3, note that
`add_permission(InvokedViaFunctionUrl=True)` is a boto3-specific parameter
with no direct AWS CLI equivalent.

#### CloudFront Returns 403 for Frontend

**Cause:** S3 bucket policy does not allow CloudFront OAC access, or the OAC
is not attached to the distribution.

**Fix:** Verify the `4-frontend.yaml` stack deployed successfully and that the
S3 bucket policy includes the `AllowCloudFrontOAC` statement referencing the
correct distribution ARN.

#### CORS Errors in Browser

**Cause:** The Lambda's `ALLOWED_ORIGINS` environment variable does not
include the CloudFront domain.

**Fix:** Update the `AllowedOrigins` parameter in the API stack, or set the
`ALLOWED_ORIGINS` Lambda environment variable to include the CloudFront URL
(e.g., `https://dxxxxxxxxxx.cloudfront.net`).

#### Cognito `FORCE_CHANGE_PASSWORD` State

**Cause:** User was created with `admin-create-user` instead of `sign_up`.

**Fix:** Delete the user and recreate using the `sign_up` flow as described
in Step 6. The `sign_up` + `admin_confirm_sign_up` combination avoids the
forced password change state entirely.

#### WAF Blocks Requests

**Cause:** Two separate WAFs are deployed:
- **REGIONAL** WAF (Stack 1) -- attached to any regional resources
- **GLOBAL/CLOUDFRONT** WAF (Stack 4) -- attached to the CloudFront distribution

**Fix:** Check WAF logs in CloudWatch. Common false positives come from
AWS managed rule groups. Adjust the WAF rules in the relevant CloudFormation
template.

### Useful Commands

```bash
# List all CloudFormation stacks
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE

# View stack outputs
aws cloudformation describe-stacks --stack-name illuminate-base-dev \
  --query 'Stacks[0].Outputs'

# Check Lambda logs
aws logs tail /aws/lambda/illuminate-api-proxy-dev --follow

# Check AgentCore agent status
agentcore list

# View SSM parameters
aws ssm get-parameters-by-path --path /illuminate/dev/ --recursive

# Invalidate CloudFront cache manually
DIST_ID=$(aws cloudformation describe-stacks --stack-name illuminate-frontend-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDistributionId`].OutputValue' \
  --output text)
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"
```

### Environment Variables Reference

| Variable | Used By | Description |
|----------|---------|-------------|
| `AWS_REGION` | All scripts | AWS region (default: `us-east-1`) |
| `SNOWFLAKE_ACCOUNT` | `.env` → `deploy-base.sh` | Snowflake account identifier |
| `SNOWFLAKE_USER` | `.env` → `deploy-base.sh` | Snowflake service user |
| `SNOWFLAKE_PASSWORD` | `.env` → `deploy-base.sh` | Snowflake password |
| `SNOWFLAKE_DATABASE` | `.env` → `deploy-base.sh` | Snowflake database name |
| `SNOWFLAKE_WAREHOUSE` | `.env` → `deploy-base.sh` | Snowflake warehouse name |
| `SNOWFLAKE_ROLE` | `.env` → `deploy-base.sh` | Snowflake role |
| `ORCHESTRATOR_ENDPOINT_URL` | Lambda | AgentCore orchestrator runtime URL |
| `USER_POOL_ID` | Lambda | Cognito User Pool ID |
| `USER_POOL_CLIENT_ID` | Lambda | Cognito App Client ID |
| `ALLOWED_ORIGINS` | Lambda | Comma-separated CORS origins |
| `VITE_API_URL` | Frontend build | API endpoint URL (Function URL) |
| `VITE_USER_POOL_ID` | Frontend build | Cognito User Pool ID |
| `VITE_USER_POOL_CLIENT_ID` | Frontend build | Cognito App Client ID |
