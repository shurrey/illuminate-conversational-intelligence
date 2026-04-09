# Illuminate POC Backend

Multi-agent AI backend for natural language access to Anthology Illuminate's educational data warehouse. Translates questions into SQL, executes against Snowflake, analyzes results, and validates for FERPA compliance.

## Architecture

```
API Clients (Frontend, Dashboard, etc.)
  |
  | HTTPS + Cognito JWT
  v
Lambda Function URL (RESPONSE_STREAM)
  |
  | Lambda Web Adapter (LWA) -> uvicorn/FastAPI
  |
  +-- /api/chat, /api/chat/stream     -> boto3 invoke_agent_runtime (SigV4)
  |                                         |
  |                                   Bedrock AgentCore (A2A Protocol)
  |                                         |
  |                                    Orchestrator (Sonnet 4.6)
  |                                         |
  |                              +----------+----------+----------+
  |                              |          |          |          |
  |                            SQL      Analyst     Writer    Validator
  |                          (Sonnet)  (Sonnet)   (Sonnet)   (Sonnet)
  |                              |
  |                           Snowflake
  |
  +-- /api/v1/dictionary/*     -> Proxy to Blackboard Data Dictionary API
  +-- /api/v1/dictionary/preview -> Direct Snowflake query
  +-- /api/v1/dashboard/query  -> Direct Snowflake query
```

All agents run as containerized runtimes on AWS Bedrock AgentCore, communicating via the A2A (Agent-to-Agent) protocol. The Lambda function is a thin proxy that forwards chat requests to the orchestrator and provides direct data access endpoints.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Proxy | AWS Lambda + Lambda Web Adapter (FastAPI, real SSE streaming) |
| Auth | Amazon Cognito (JWT) |
| Agent Runtime | AWS Bedrock AgentCore (ARM64 containers) |
| Agent Framework | Strands Agents SDK (A2A protocol) |
| LLM | Claude Sonnet 4.6 (via Amazon Bedrock) |
| Data Warehouse | Snowflake |
| Infrastructure | AWS CDK (TypeScript, 3 stacks) |
| Service Discovery | SSM Parameter Store |

## Quick Start

```bash
# Prerequisites: AWS CLI, Python 3.11+, Node.js 18+, Docker, CDK CLI

# 1. Configure
cp .env.example .env
# Edit .env with Snowflake credentials and initial user

# 2. Deploy everything
cd cdk
npm install
npx cdk bootstrap   # first time only
npx cdk deploy --all
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full instructions.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/api/chat` | POST | JWT | Send message, get complete response |
| `/api/chat/stream` | POST | JWT | Send message, get SSE stream |
| `/api/v1/dictionary/submodels` | GET | JWT | CDM domain listing |
| `/api/v1/dictionary/definitions` | GET | JWT | Column definitions (1,617 entries) |
| `/api/v1/dictionary/erd` | GET | JWT | Entity relationships |
| `/api/v1/dictionary/preview` | GET | JWT | Sample table data from Snowflake |
| `/api/v1/dashboard/query` | POST | JWT | Execute read-only SQL |

See [docs/API.md](docs/API.md) for full reference.

## Project Structure

```
illuminate-poc-backend/
├── agents/                    # 5 self-contained A2A agents
│   ├── Dockerfile             # Shared Dockerfile (uv + Python 3.13)
│   ├── orchestrator/          # Coordinator — routes to specialists
│   ├── sql/                   # SQL generation & Snowflake execution
│   ├── analyst/               # Data analysis & interpretation
│   ├── writer/                # Response composition
│   └── validator/             # FERPA compliance validation
├── cdk/                       # AWS CDK infrastructure (TypeScript)
│   ├── bin/illuminate.ts      # App entry — reads .env, deploys 3 stacks
│   └── lib/
│       ├── base/              # VPC, Cognito, S3, Secrets, WAF, SSM
│       ├── agentcore/         # IAM, Memory (STM), 5x container runtimes
│       └── api/               # Lambda + LWA + Function URL
├── lambda_handler.py          # FastAPI proxy (chat, dictionary, dashboard)
├── snowflake_client.py        # Lazy Snowflake connection for direct queries
├── run.sh                     # LWA startup script
├── requirements-lambda.txt    # Lambda Python dependencies
├── .env.example               # Environment template
└── docs/                      # Documentation
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design, agent responsibilities, data flow
- [Deployment Guide](docs/DEPLOYMENT.md) - Setup and deployment instructions
- [API Reference](docs/API.md) - Endpoint contracts and response shapes
- [Development Guide](docs/DEVELOPMENT.md) - Agent development, modifying the system
- [Product Spec](SPEC.md) - Original product requirements (with implementation notes)

## SSM Discovery Parameters

All service endpoints and IDs are published to SSM Parameter Store at `/illuminate/{env}/`:

```
cognito-pool-id, cognito-client-id, api-url, orchestrator-arn,
sql-arn, analyst-arn, writer-arn, validator-arn, memory-id,
artifacts-bucket, snowflake-secret-arn
```

Other services (frontend, dashboard) read these to discover backend resources.
