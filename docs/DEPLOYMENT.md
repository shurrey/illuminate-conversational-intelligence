# Illuminate Conversational Intelligence - Deployment Guide

This document describes how to deploy the Illuminate ICI platform from scratch
and how to update individual components after the initial deployment.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Initial Setup (Environment Configuration)](#2-initial-setup-environment-configuration)
3. [CDK Deployment (Primary)](#3-cdk-deployment-primary)
4. [Frontend Deployment](#4-frontend-deployment)
5. [Verification](#5-verification)
6. [Updating Individual Components](#6-updating-individual-components)
7. [Legacy CloudFormation Deployment](#7-legacy-cloudformation-deployment)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

### Required Tools

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI v2 | Latest | AWS operations and credential management |
| Python | 3.11+ | Lambda handler, virtual environment |
| Node.js | 18+ | CDK CLI, frontend build (React + Vite) |
| npm | Bundled with Node.js | CDK and frontend dependency management |
| Docker | Latest | Building agent container images (ARM64) |
| AWS CDK CLI | Latest | Infrastructure deployment (`npm install -g aws-cdk`) |

### AWS Permissions

The deploying IAM principal needs permissions for:

- CloudFormation (CDK uses CloudFormation under the hood)
- IAM (create roles, attach policies)
- S3 (create buckets, upload objects)
- ECR (create repositories, push images)
- Lambda (create/update functions)
- CloudFront (create distributions, invalidate cache)
- Cognito (create user pools)
- Secrets Manager (create/read secrets)
- WAF v2 (create web ACLs -- both REGIONAL and CLOUDFRONT scopes)
- SSM Parameter Store (put/get parameters)
- Bedrock (model access)
- Bedrock AgentCore (create/invoke runtimes, manage memory)

### CDK Bootstrap

If this is the first time using CDK in the target account/region, bootstrap it:

```bash
npx cdk bootstrap aws://856599266077/us-east-1
```

### Bedrock Model Access

Before deploying, enable access to the following model in the **us-east-1**
region via the Bedrock console (Model Access page):

- **Claude Sonnet 4.6** (`us.anthropic.claude-sonnet-4-6`) -- cross-region inference profile

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

## 2. Initial Setup (Environment Configuration)

Create a `.env` file from the provided example:

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
INITIAL_USER_EMAIL=admin@example.com
INITIAL_USER_PASSWORD=YourSecurePassword123!
```

The `.env` file is read automatically by the CDK app (`cdk/bin/illuminate.ts`).
Snowflake credentials are stored in AWS Secrets Manager at
`illuminate/{env}/snowflake`. The initial user is created in Cognito via an
`AwsCustomResource` on the first deploy.

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

## 3. CDK Deployment (Primary)

Infrastructure is managed via **AWS CDK** (TypeScript) organized into three
stacks. CDK reads configuration from `.env` automatically -- no `-c` context
flags are needed.

### Deploy Everything

```bash
cd cdk
npm install
npx cdk deploy --all
```

This deploys all three stacks in dependency order:

1. **IlluminateBase-dev** -- VPC, Cognito (LITE tier), S3, Secrets Manager, WAF, SSM discovery parameters
2. **IlluminateAgentCore-dev** -- IAM role, Memory (STM), 5x Docker container runtimes (built via `DockerImageAsset`, pushed to ECR)
3. **IlluminateAPI-dev** -- Lambda + Lambda Web Adapter + Function URL (`RESPONSE_STREAM`)

### Deploy Individual Stacks

```bash
cd cdk

# Stack 1: Base infrastructure
npx cdk deploy IlluminateBase-dev

# Stack 2: AgentCore (builds Docker images -- requires Docker running)
npx cdk deploy IlluminateAgentCore-dev

# Stack 3: API Lambda
npx cdk deploy IlluminateAPI-dev
```

### What CDK Creates

| Stack | Key Resources |
|-------|---------------|
| `IlluminateBase-dev` | VPC (public + private subnets, NAT Gateway), Cognito User Pool + App Client (LITE tier), S3 artifacts bucket, Secrets Manager (Snowflake creds), REGIONAL WAF, SSM parameters, initial Cognito user |
| `IlluminateAgentCore-dev` | IAM execution role (bedrock, secrets, memory, logs), AgentCore Memory (STM, 24h expiry), 5x `DockerImageAsset` (ECR push), 5x `CfnRuntime` (container runtimes), SSM parameters for all agent ARNs |
| `IlluminateAPI-dev` | Lambda function (Python 3.13, 1024 MB, 900s timeout, VPC), Lambda Layer (LWA), Function URL (`RESPONSE_STREAM`), IAM execution role, Log group |

### Important Notes

- **Docker must be running** before deploying `IlluminateAgentCore-dev`. CDK builds ARM64 Docker images locally for each agent.
- **First deploy takes longer** because all Docker images must be built and pushed to ECR.
- **Subsequent deploys** only rebuild images if the agent source code or Dockerfile changed.

---

## 4. Frontend Deployment

The frontend is a React 18 + TypeScript application built with Vite and styled
with TailwindCSS. It authenticates users via Cognito
(`amazon-cognito-identity-js`).

The CDK stack for the frontend exists in `cdk/lib/frontend/` but is currently
deployed separately using the legacy script.

### Deploy Command

```bash
infrastructure/scripts/deploy-frontend.sh dev
```

The script:

1. Reads backend configuration from SSM / CloudFormation stack outputs:
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

## 5. Verification

### Health Check

After deploying the API stack, verify the Lambda is reachable:

```bash
# Get the Function URL from SSM
API_URL=$(aws ssm get-parameter \
  --name /illuminate/dev/api-url \
  --query 'Parameter.Value' \
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

Check that agents are running via the AgentCore console or CLI. All five
container runtimes should be in ACTIVE state.

### End-to-End Test

1. Open the CloudFront URL in a browser
2. Log in with the initial Cognito user (created during CDK deploy)
3. Send a test message like "What tables are available?"
4. Verify you receive a response with real-time status updates and a final answer

---

## 6. Updating Individual Components

### Update Agent Code Only

Modify the agent's `a2a_server.py`, then redeploy the AgentCore stack:

```bash
cd cdk
npx cdk deploy IlluminateAgentCore-dev
```

CDK will detect which Docker images changed and only rebuild those.

### Update Lambda Code Only

```bash
cd cdk
npx cdk deploy IlluminateAPI-dev
```

### Update Frontend Only

Rebuild and redeploy the frontend without touching infrastructure:

```bash
infrastructure/scripts/deploy-frontend.sh dev
```

This builds the React app, syncs to S3, and invalidates CloudFront.

### Update Base Infrastructure

```bash
cd cdk
npx cdk deploy IlluminateBase-dev
```

### Full Redeploy

```bash
cd cdk
npx cdk deploy --all

# Then frontend (deployed separately)
cd ..
infrastructure/scripts/deploy-frontend.sh dev
```

---

## 7. Legacy CloudFormation Deployment

> **Note:** This section documents the original CloudFormation + shell script
> deployment approach. It is still functional but has been **superseded by CDK**
> for all stacks except the frontend.

Infrastructure was originally managed via four CloudFormation stacks deployed
in order. All templates live in `infrastructure/cloudformation/`.

### Deployment Order

```
1-base-infrastructure.yaml
        |
        v
2-agentcore.yaml
        |
        v
3-api-gateway.yaml  (requires agent URLs in SSM)
        |
        v
4-frontend.yaml
```

### Deploy Commands

```bash
# Stack 1: Base infrastructure
infrastructure/scripts/deploy-base.sh dev

# Stack 2: AgentCore CloudFormation resources
infrastructure/scripts/deploy-agentcore.sh dev

# Stack 3: API Lambda + Function URL
infrastructure/scripts/deploy-api.sh dev

# Stack 4: Frontend
infrastructure/scripts/deploy-frontend.sh dev
```

---

## 8. Troubleshooting

### Common Errors

#### CDK Deploy Fails: "Docker is not running"

**Cause:** The AgentCore stack builds Docker images locally via `DockerImageAsset`.

**Fix:** Start Docker Desktop or the Docker daemon before running `npx cdk deploy`.

#### CDK Deploy Fails: "Cannot assume role"

**Cause:** CDK has not been bootstrapped in the target account/region.

**Fix:**
```bash
npx cdk bootstrap aws://856599266077/us-east-1
```

#### Container Build Fails (ARM64 issues on x86)

**Cause:** Building ARM64 images on an x86 machine without QEMU emulation.

**Fix:** Enable Docker buildx with QEMU:
```bash
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```
On macOS with Docker Desktop, ARM64 builds work natively on Apple Silicon.

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
- Check that `a2a_server.py` binds to port 8080.
- Look for runtime exceptions in CloudWatch logs.
- Ensure all Python dependencies are listed in the agent's `requirements.txt`.

#### "Init time exceeded" from AgentCore

**Cause:** Agent startup takes too long (heavy imports, slow initialization).

**Fix:**
- Minimize imports at module level.
- Defer heavy initialization (model loading, database connections) to first
  request rather than module load time.

#### Lambda Function URL Returns 403

**Cause:** Missing invocation permissions. Lambda Function URLs with
`AuthType: NONE` require **two** permissions:
1. `lambda:InvokeFunctionUrl` (standard)
2. `lambda:InvokeFunction` with condition `lambda:InvokedViaFunctionUrl: true`

**Fix:** Verify both permissions exist in the CDK API stack.

#### CloudFront Returns 403 for Frontend

**Cause:** S3 bucket policy does not allow CloudFront OAC access, or the OAC
is not attached to the distribution.

**Fix:** Verify the frontend CloudFormation stack deployed successfully and that
the S3 bucket policy includes the `AllowCloudFrontOAC` statement referencing
the correct distribution ARN.

#### CORS Errors in Browser

**Cause:** The Lambda's `ALLOWED_ORIGINS` environment variable does not
include the CloudFront domain.

**Fix:** Update the `AllowedOrigins` in the CDK API stack, or set the
`ALLOWED_ORIGINS` Lambda environment variable to include the CloudFront URL
(e.g., `https://dxxxxxxxxxx.cloudfront.net`).

#### Cognito `FORCE_CHANGE_PASSWORD` State

**Cause:** User was created with `admin-create-user` instead of `sign_up`.

**Fix:** Delete the user and recreate using the `sign_up` flow. The CDK base
stack creates the initial user via `sign_up` + `admin_confirm_sign_up` using
an `AwsCustomResource`, which avoids the forced password change state.

#### WAF Blocks Requests

**Cause:** Two separate WAFs are deployed:
- **REGIONAL** WAF (Base stack) -- attached to any regional resources
- **GLOBAL/CLOUDFRONT** WAF (Frontend stack) -- attached to the CloudFront distribution

**Fix:** Check WAF logs in CloudWatch. Common false positives come from
AWS managed rule groups. Adjust the WAF rules in the relevant CDK or
CloudFormation stack.

#### STM Session Not Found

**Cause:** The `runtimeSessionId` in the `invoke_agent_runtime` call does
not match an existing STM session, or the memory resource is not provisioned.

**Fix:**
- Verify the memory resource exists: check SSM parameter `/illuminate/{env}/memory-id`.
- Check that the Lambda is passing `runtimeSessionId` (the `context_id` from the frontend).
- Verify the IAM role has `bedrock:RetrieveMemorySession` and `bedrock:CreateMemorySession` permissions.

### Useful Commands

```bash
# List all CDK stacks
cd cdk && npx cdk list

# Show CDK diff before deploying
cd cdk && npx cdk diff

# List all CloudFormation stacks
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE

# View stack outputs
aws cloudformation describe-stacks --stack-name IlluminateBase-dev \
  --query 'Stacks[0].Outputs'

# Check Lambda logs
aws logs tail /aws/lambda/illuminate-api-proxy-dev --follow

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
| `AWS_REGION` | CDK, all scripts | AWS region (default: `us-east-1`) |
| `SNOWFLAKE_ACCOUNT` | `.env` -> CDK | Snowflake account identifier |
| `SNOWFLAKE_USER` | `.env` -> CDK | Snowflake service user |
| `SNOWFLAKE_PASSWORD` | `.env` -> CDK | Snowflake password |
| `SNOWFLAKE_DATABASE` | `.env` -> CDK | Snowflake database name |
| `SNOWFLAKE_WAREHOUSE` | `.env` -> CDK | Snowflake warehouse name |
| `SNOWFLAKE_ROLE` | `.env` -> CDK | Snowflake role |
| `INITIAL_USER_EMAIL` | `.env` -> CDK | Email for the first Cognito user |
| `INITIAL_USER_PASSWORD` | `.env` -> CDK | Password for the first Cognito user |
| `ORCHESTRATOR_RUNTIME_ARN` | Lambda (via SSM) | AgentCore orchestrator runtime ARN |
| `USER_POOL_ID` | Lambda (via SSM) | Cognito User Pool ID |
| `USER_POOL_CLIENT_ID` | Lambda (via SSM) | Cognito App Client ID |
| `MEMORY_ID` | Lambda (via SSM) | AgentCore Memory resource ID |
| `ALLOWED_ORIGINS` | Lambda | Comma-separated CORS origins |
| `VITE_API_URL` | Frontend build | API endpoint URL (Function URL) |
| `VITE_USER_POOL_ID` | Frontend build | Cognito User Pool ID |
| `VITE_USER_POOL_CLIENT_ID` | Frontend build | Cognito App Client ID |
