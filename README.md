# Illuminate Conversational Intelligence

Natural language access to Anthology Illuminate's educational data warehouse. Ask questions in plain English, get SQL-backed answers with charts and analysis.

## What It Does

A multi-agent AI system that lets institutional researchers, academic advisors, and administrators explore educational data through conversation:

- **Ask questions naturally**: "What's the average GPA for Fall 2024?" or "Show me enrollment trends by department"
- **Get real answers**: Queries are translated to SQL, executed against Snowflake, and results are analyzed
- **Visualize data**: Request charts and the system generates interactive Plotly visualizations
- **View the SQL**: Every query is surfaced as a navigable SQL artifact so you can see exactly what ran
- **Follow up**: Conversation context is maintained across turns via AgentCore Short-Term Memory (STM)
- **FERPA compliant**: A dedicated validator agent checks every response for PII exposure

## Architecture

```
Browser (React + TypeScript)
  |
  | HTTPS
  v
CloudFront (static files) + Lambda Function URL (API)
  |
  | boto3 SigV4
  v
Bedrock AgentCore (A2A Protocol)
  |
  +-- Orchestrator (Claude Sonnet 4.6) -- coordinates the pipeline
  |     |
  |     +-- SQL Agent (Claude Sonnet 4.6) -- generates & executes Snowflake queries
  |     +-- Analyst Agent (Claude Sonnet 4.6) -- interprets query results
  |     +-- Writer Agent (Claude Sonnet 4.6) -- crafts human-readable responses
  |     +-- Validator Agent (Claude Sonnet 4.6) -- FERPA/PII compliance check
  |
  v
Snowflake Data Warehouse
```

All agents run as containerized runtimes on AWS Bedrock AgentCore, communicating via the A2A (Agent-to-Agent) protocol. The Lambda function is a thin proxy that forwards requests to the orchestrator using Lambda Web Adapter (LWA) for real SSE streaming.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, TailwindCSS |
| Charts | Plotly.js via react-plotly.js |
| SQL Display | sql-formatter |
| Auth | Amazon Cognito (JWT) |
| API Proxy | AWS Lambda (Python 3.13, FastAPI, Lambda Web Adapter) |
| Agent Runtime | AWS Bedrock AgentCore (Docker containers, ARM64) |
| Agent Framework | Strands Agents SDK (A2A protocol) |
| LLM | Claude Sonnet 4.6 (via Amazon Bedrock cross-region inference) |
| Data Warehouse | Snowflake |
| Infrastructure | AWS CDK (TypeScript, 3 stacks) |

## Quick Start

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full deployment instructions.

```bash
# Prerequisites: AWS CLI configured, Python 3.11+, Node.js 18+, Docker, AWS CDK CLI

# 1. Configure environment
cp .env.example .env
# Edit .env with your Snowflake credentials and settings

# 2. Deploy all infrastructure (Base + AgentCore + API)
cd cdk
npm install
npx cdk deploy --all

# 3. Deploy frontend (currently deployed separately)
cd ../infrastructure/scripts
./deploy-frontend.sh dev
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design, agent responsibilities, data flow
- [Deployment Guide](docs/DEPLOYMENT.md) - Step-by-step setup and deployment
- [API Reference](docs/API.md) - Lambda proxy endpoints and request/response formats
- [Development Guide](docs/DEVELOPMENT.md) - Project structure, modifying agents, adding new agents
- [Product Spec](SPEC.md) - Original product requirements document

## Project Structure

```
illuminate-ici/
├── agents/                    # 5 self-contained A2A agents
│   ├── Dockerfile             # Shared Dockerfile (uv + Python 3.13, ARM64)
│   ├── orchestrator/          # Central coordinator
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── Dockerfile -> ../Dockerfile
│   ├── sql/                   # SQL generation & Snowflake execution
│   ├── analyst/               # Data analysis & interpretation
│   ├── writer/                # Response composition
│   └── validator/             # FERPA compliance validation
├── cdk/                       # AWS CDK infrastructure (TypeScript)
│   ├── bin/illuminate.ts      # App entry point -- 3 stacks, reads .env
│   ├── lib/
│   │   ├── base/              # VPC, Cognito, S3, Secrets, WAF, SSM
│   │   ├── agentcore/         # IAM, Memory (STM), 5x container runtimes
│   │   ├── api/               # Lambda + LWA + Function URL (RESPONSE_STREAM)
│   │   └── frontend/          # S3 + CloudFront (deployed separately)
│   └── package.json
├── infrastructure/            # Legacy CloudFormation + shell scripts
│   ├── cloudformation/        # 4 YAML stacks (superseded by CDK)
│   └── scripts/               # Deploy/teardown scripts
├── frontend/                  # React SPA
│   └── src/
│       ├── components/
│       │   ├── chat/           # MessageBubble, InputArea, etc.
│       │   └── visualization/  # ChartRenderer, DataTable, SqlModal
│       ├── hooks/useChat.ts
│       ├── services/           # agentClient, authService
│       └── types/              # message.ts, visualization.ts
├── lambda_handler.py          # FastAPI proxy (runs via LWA, NOT Mangum)
├── run.sh                     # LWA startup script (uvicorn)
├── requirements-lambda.txt    # Lambda Python dependencies
├── .env                       # Local config (gitignored)
├── .env.example
└── docs/
```

## Example Queries

- "What schemas are available in the database?"
- "Show me the tables in CDM_LMS"
- "What is the average GPA for Fall 2024?"
- "Show me a bar chart of tables by schema"
- "Now break that down by department" (follow-up)
