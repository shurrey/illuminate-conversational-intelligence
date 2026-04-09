# Illuminate POC Backend - Deployment Guide

This document describes how to deploy the Illuminate POC Backend from scratch
and how to update individual components after the initial deployment.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Initial Setup (Environment Configuration)](#2-initial-setup-environment-configuration)
3. [CDK Deployment](#3-cdk-deployment)
4. [Verification](#4-verification)
5. [Updating Individual Components](#5-updating-individual-components)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Prerequisites

### Required Tools

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI v2 | Latest | AWS operations and credential management |
| Python | 3.11+ | Lambda handler, virtual environment |
| Node.js | 18+ | CDK CLI |
| npm | Bundled with Node.js | CDK dependency management |
| Docker | Latest | Building agent container images (ARM64) |
| AWS CDK CLI | Latest | Infrastructure deployment (`npm install -g aws-cdk`) |

### AWS Permissions

The deploying IAM principal needs permissions for:

- CloudFormation (CDK uses CloudFormation under the hood)
- IAM (create roles, attach policies)
- S3 (create buckets, upload objects)
- ECR (create repositories, push images)
- Lambda (create/update functions)
- Cognito (create user pools)
- Secrets Manager (create/read secrets)
- WAF v2 (create web ACLs -- REGIONAL scope)
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

## 3. CDK Deployment

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

## 4. Verification

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

### Agent Health

Check that agents are running via the AgentCore console or CLI. All five
container runtimes should be in ACTIVE state.

### End-to-End Test

1. Obtain a Cognito JWT token (sign in via the Cognito User Pool)
2. Send a test request to the streaming endpoint:
   ```bash
   curl -N "$API_URL/api/chat/stream" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"message": "What tables are available?", "context_id": "test-123"}'
   ```
3. Verify you receive SSE events with real-time status updates and a final `complete` event

---

## 5. Updating Individual Components

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

### Update Base Infrastructure

```bash
cd cdk
npx cdk deploy IlluminateBase-dev
```

### Full Redeploy

```bash
cd cdk
npx cdk deploy --all
```

---

## 6. Troubleshooting

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

#### Cognito `FORCE_CHANGE_PASSWORD` State

**Cause:** User was created with `admin-create-user` instead of `sign_up`.

**Fix:** Delete the user and recreate using the `sign_up` flow. The CDK base
stack creates the initial user via `sign_up` + `admin_confirm_sign_up` using
an `AwsCustomResource`, which avoids the forced password change state.

#### STM Session Not Found

**Cause:** The `runtimeSessionId` in the `invoke_agent_runtime` call does
not match an existing STM session, or the memory resource is not provisioned.

**Fix:**
- Verify the memory resource exists: check SSM parameter `/illuminate/{env}/memory-id`.
- Check that the Lambda is passing `runtimeSessionId` (the `context_id` from the client).
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
```

### Environment Variables Reference

| Variable | Used By | Description |
|----------|---------|-------------|
| `AWS_REGION` | CDK | AWS region (default: `us-east-1`) |
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
