# Illuminate Conversational Intelligence

Natural language access to Anthology Illuminate's educational data warehouse. Ask questions in plain English, get SQL-backed answers with charts and analysis.

## What It Does

A multi-agent AI system that lets institutional researchers, academic advisors, and administrators explore educational data through conversation:

- **Ask questions naturally**: "What's the average GPA for Fall 2024?" or "Show me enrollment trends by department"
- **Get real answers**: Queries are translated to SQL, executed against Snowflake, and results are analyzed
- **Visualize data**: Request charts and the system generates interactive Plotly visualizations
- **Follow up**: Conversation context is maintained across turns
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
  +-- Orchestrator (Claude Sonnet) -- coordinates the pipeline
  |     |
  |     +-- SQL Agent (Claude Opus) -- generates & executes Snowflake queries
  |     +-- Analyst Agent (Claude Opus) -- interprets query results
  |     +-- Writer Agent (Claude Sonnet) -- crafts human-readable responses
  |     +-- Validator Agent (Claude Sonnet) -- FERPA/PII compliance check
  |
  v
Snowflake Data Warehouse
```

All agents run as self-contained runtimes on AWS Bedrock AgentCore, communicating via the A2A (Agent-to-Agent) protocol. The Lambda function is a thin proxy that forwards requests to the orchestrator.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, TailwindCSS |
| Charts | Plotly.js via react-plotly.js |
| Auth | Amazon Cognito (JWT) |
| API Proxy | AWS Lambda (Python 3.11, FastAPI, Mangum) |
| Agent Runtime | AWS Bedrock AgentCore |
| Agent Framework | Strands Agents SDK (A2A protocol) |
| LLM | Claude Sonnet 4 / Claude Opus 4 (via Amazon Bedrock) |
| Data Warehouse | Snowflake |
| Infrastructure | CloudFormation (4 stacks), CloudFront, S3, WAF |

## Quick Start

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full deployment instructions.

```bash
# Prerequisites: AWS CLI configured, Python 3.11+, Node.js 18+, agentcore CLI

# 1. Deploy AWS infrastructure
cd infrastructure/scripts
./deploy.sh dev

# 2. Deploy agents to Bedrock AgentCore
cd ../
./agentcore-deploy.sh

# 3. Deploy frontend
cd scripts/
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
├── agents/                    # Agent source code (deployed to AgentCore)
│   ├── orchestrator/          #   Central coordinator
│   ├── sql/                   #   SQL generation & Snowflake execution
│   ├── analyst/               #   Data analysis & interpretation
│   ├── writer/                #   Response composition
│   └── validator/             #   FERPA compliance validation
├── frontend/                  # React frontend
│   ├── src/
│   │   ├── components/        #   Chat, layout, visualization components
│   │   ├── services/          #   API client, auth service
│   │   ├── hooks/             #   Custom React hooks (useChat)
│   │   └── types/             #   TypeScript type definitions
│   ├── .env.development       #   Dev environment config
│   └── .env.production        #   Production environment config
├── infrastructure/            # AWS deployment
│   ├── cloudformation/        #   4 CloudFormation YAML stacks
│   ├── scripts/               #   Deployment shell scripts
│   └── agentcore-deploy.sh    #   Agent deployment to AgentCore
├── lambda_handler.py          # Lambda proxy (FastAPI + Mangum)
├── requirements-lambda.txt    # Lambda Python dependencies
├── docs/                      # Documentation
└── SPEC.md                    # Product requirements document
```

## Example Queries

- "What schemas are available in the database?"
- "Show me the tables in CDM_LMS"
- "What is the average GPA for Fall 2024?"
- "Show me a bar chart of tables by schema"
- "Now break that down by department" (follow-up)

## License

Proprietary - Anthology Inc.
