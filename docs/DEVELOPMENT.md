# Illuminate Conversational Intelligence - Developer Guide

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Environment Setup](#environment-setup)
- [Agent Development](#agent-development)
  - [How Agents Work](#how-agents-work)
  - [Modifying an Existing Agent](#modifying-an-existing-agent)
  - [Adding a New Agent](#adding-a-new-agent)
  - [Critical Constraint: Self-Contained Code](#critical-constraint-self-contained-code)
  - [Agent Communication Pattern](#agent-communication-pattern)
- [Frontend Development](#frontend-development)
  - [Tech Stack](#tech-stack)
  - [Key Source Files](#key-source-files)
  - [Building the Frontend](#building-the-frontend)
  - [Chat and Streaming](#chat-and-streaming)
  - [Visualization Pipeline](#visualization-pipeline)
- [Lambda Proxy](#lambda-proxy)
- [Infrastructure](#infrastructure)
  - [CDK Stacks](#cdk-stacks)
  - [Request Flow](#request-flow)
- [Important Patterns and Gotchas](#important-patterns-and-gotchas)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

Illuminate is a multi-agent conversational intelligence system that lets users query
Snowflake data using natural language. The system is composed of:

1. **Frontend** - React SPA served from S3 via CloudFront
2. **Lambda Proxy** - Thin FastAPI handler running via Lambda Web Adapter (LWA) that
   validates Cognito JWTs and forwards requests to the orchestrator with real SSE streaming
3. **Orchestrator Agent** - Coordinates specialist agents to fulfill user queries
4. **Specialist Agents** - SQL, Analyst, Writer, and Validator, each running as
   independent Bedrock AgentCore container runtimes using the A2A (Agent-to-Agent) protocol

All agent code runs in AWS Bedrock AgentCore as Docker containers (ARM64). There is no
local development server for the backend -- both dev and prod environments are AWS-hosted.

```
User -> CloudFront -> S3 (static files)
User -> CloudFront -> Lambda Function URL -> Lambda Proxy (LWA) -> Orchestrator AgentCore
                                                                        |
                                                       +----------------+----------------+
                                                       |        |       |                |
                                                     SQL    Analyst   Writer         Validator
                                                  (AgentCore container runtimes, A2A protocol)
```

## Project Structure

```
/
├── agents/
│   ├── Dockerfile              # Shared Dockerfile (uv + Python 3.13, ARM64)
│   ├── orchestrator/           # Coordinates specialist agents
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── Dockerfile -> ../Dockerfile
│   ├── sql/                    # Generates and executes Snowflake SQL
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── Dockerfile -> ../Dockerfile
│   ├── analyst/                # Data analysis and interpretation
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── Dockerfile -> ../Dockerfile
│   ├── writer/                 # Narrative report generation
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── Dockerfile -> ../Dockerfile
│   └── validator/              # Result validation and quality checks
│       ├── a2a_server.py
│       ├── requirements.txt
│       └── Dockerfile -> ../Dockerfile
├── cdk/                        # AWS CDK infrastructure (TypeScript)
│   ├── bin/illuminate.ts       # App entry point -- 3 stacks, reads .env
│   ├── lib/
│   │   ├── base/               # VPC, Cognito, S3, Secrets, WAF, SSM
│   │   ├── agentcore/          # IAM, Memory (STM), 5x container runtimes
│   │   ├── api/                # Lambda + LWA + Function URL
│   │   └── frontend/           # S3 + CloudFront (deployed separately)
│   └── package.json
├── infrastructure/             # Legacy CloudFormation + shell scripts
│   ├── cloudformation/         # 4 CF templates (superseded by CDK)
│   └── scripts/                # Deployment helper scripts
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── auth/            # Login, auth guards
│   │   │   ├── chat/            # ChatContainer, MessageBubble, InputArea, etc.
│   │   │   ├── layout/          # AppShell, Header, Sidebar
│   │   │   └── visualization/   # ChartRenderer, DataTable, ExportButton, SqlModal
│   │   ├── hooks/
│   │   │   └── useChat.ts       # Main chat state management
│   │   ├── services/
│   │   │   ├── agentClient.ts   # API client (fetch + ReadableStream for SSE)
│   │   │   └── authService.ts   # Cognito auth via amazon-cognito-identity-js
│   │   └── types/
│   │       ├── message.ts       # Message, Artifact, StreamingEvent types
│   │       └── visualization.ts # Chart config types, chartConfigToPlotly()
│   ├── package.json
│   └── tsconfig.json
├── lambda_handler.py            # API proxy Lambda (FastAPI + LWA)
├── run.sh                       # LWA startup script (uvicorn on port 8080)
├── requirements-lambda.txt      # Lambda Python dependencies
└── docs/
    └── DEVELOPMENT.md           # This file
```

## Environment Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (for building agent container images)
- AWS CLI configured with credentials for account 856599266077
- AWS CDK CLI (`npm install -g aws-cdk`)
- Access to the `illuminate-agent-role-dev` IAM role

### Python Environment

```bash
# From the project root
source .venv/bin/activate
```

The project uses a `.venv` directory.

### Frontend Environment

```bash
cd frontend
npm install
```

### Building the Frontend

```bash
cd frontend
npx vite build --mode development
```

There is no local dev server that connects to live backends. The `VITE_API_URL`
environment variable must point to the deployed Function URL for all API calls.

## Agent Development

### How Agents Work

Each agent is a self-contained Python application that:

1. Defines `@tool`-decorated functions as capabilities
2. Creates a **Strands Agent** with a system prompt and tools
3. Builds an ASGI app via `build_a2a_app(agent)` from `strands_a2a.a2a`
4. Listens on **port 8080** (LWA / container convention)
5. Is deployed to **Bedrock AgentCore** as a Docker container runtime

The orchestrator agent is special: it uses `@tool`-decorated functions that
internally call other agents via `boto3.client("bedrock-agent-runtime").invoke_agent_runtime()`.
This is how agent-to-agent communication works -- through SigV4-authenticated
AWS SDK calls, not direct network connections.

### Modifying an Existing Agent

1. Edit the agent's `a2a_server.py` file:
   ```bash
   # Example: modify the SQL agent
   vim agents/sql/a2a_server.py
   ```

2. Deploy the updated agent via CDK:
   ```bash
   cd cdk
   npx cdk deploy IlluminateAgentCore-dev
   ```

   CDK will detect which Docker images changed and only rebuild those.

### Adding a New Agent

1. Create the agent directory:
   ```bash
   mkdir agents/myagent
   ```

2. Create a Dockerfile symlink:
   ```bash
   cd agents/myagent
   ln -s ../Dockerfile Dockerfile
   ```

3. Write `agents/myagent/a2a_server.py` following this pattern:

   ```python
   """
   MyAgent - Self-contained A2A server for AgentCore deployment.
   Zero `from agents.*` imports.
   """
   import os
   import sys

   def log(msg):
       print(msg, file=sys.stderr, flush=True)

   try:
       log("Initializing MyAgent ...")
       from strands import Agent, tool
       from strands.models.bedrock import BedrockModel
       from strands_a2a.a2a import build_a2a_app

       @tool
       def my_capability(input_text: str) -> str:
           """Description of what this tool does."""
           # Implementation here
           return "result"

       model = BedrockModel(
           model_id=os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
           region_name=os.environ.get("AWS_REGION", "us-east-1"),
       )

       agent = Agent(
           model=model,
           tools=[my_capability],
           system_prompt="You are a specialist agent that ...",
       )

       app = build_a2a_app(agent)
       log("MyAgent initialized successfully")

   except Exception as e:
       log(f"STARTUP ERROR: {e}")
       from starlette.applications import Starlette
       from starlette.responses import JSONResponse
       from starlette.routing import Route

       async def error_health(request):
           return JSONResponse({"status": "error", "error": str(e)})

       app = Starlette(routes=[Route("/health", error_health)])

   if __name__ == "__main__":
       import uvicorn
       uvicorn.run(app, host="0.0.0.0", port=8080)
   ```

4. Write `agents/myagent/requirements.txt`:
   ```
   strands-agents[a2a]
   strands-agents-tools
   bedrock-agentcore
   fastapi>=0.115.0
   uvicorn>=0.32.0
   pydantic>=2.0.0
   boto3>=1.34.0
   ```

5. Add the agent to the CDK AgentCore stack in `cdk/lib/agentcore/`. This
   involves adding a new `DockerImageAsset` and `CfnRuntime` resource.

6. Deploy:
   ```bash
   cd cdk
   npx cdk deploy IlluminateAgentCore-dev
   ```

7. Register the new agent in the orchestrator by adding a tool function to
   `agents/orchestrator/a2a_server.py`:

   ```python
   @tool
   def call_myagent(request: str) -> str:
       """Call the MyAgent specialist for ..."""
       return invoke_specialist(
           agentcore_client,
           os.environ["MYAGENT_RUNTIME_ARN"],
           request,
       )
   ```

   Add the new tool to the orchestrator's `tools` list and add the runtime ARN
   as an environment variable in the CDK AgentCore stack.

### Critical Constraint: Self-Contained Code

**Every `a2a_server.py` must be completely self-contained with zero cross-agent
imports.** This means:

- No `from agents.shared import ...`
- No `from agents.sql import ...`
- No relative imports referencing other agent directories

Each agent is built into its own Docker container. There is no shared
filesystem between agents.

If you need shared utility code, copy it directly into each agent's
`a2a_server.py` file.

### Agent Communication Pattern

The orchestrator communicates with specialist agents through the
`invoke_specialist()` function, which:

1. Constructs a JSON-RPC 2.0 payload following the A2A protocol
2. Calls `boto3.client("bedrock-agent-runtime").invoke_agent_runtime()`
3. Parses the A2A response, extracting text from artifacts, message parts, or history

```python
# Simplified view of the invoke pattern
payload = {
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "parts": [{"kind": "text", "text": message}],
        }
    },
    "id": str(uuid.uuid4()),
}

response = client.invoke_agent_runtime(
    agentRuntimeArn=runtime_arn,
    contentType="application/json",
    accept="application/json",
    payload=json.dumps(payload).encode(),
)
```

Agent runtime ARNs are configured via environment variables set in the CDK
AgentCore stack and passed to each container runtime.

## Frontend Development

### Tech Stack

- **React 18** with TypeScript
- **Vite** for build tooling
- **TailwindCSS** for styling
- **Plotly.js** (via react-plotly.js) for chart rendering
- **sql-formatter** for SQL display in SqlModal
- **react-markdown** with remark-gfm for markdown rendering
- **amazon-cognito-identity-js** for Cognito authentication

### Key Source Files

| File | Purpose |
|------|---------|
| `src/App.tsx` | Root component, routing, auth state |
| `src/services/agentClient.ts` | API client; sends messages, handles SSE streams |
| `src/services/authService.ts` | Cognito sign-in/sign-up/token management |
| `src/hooks/useChat.ts` | Chat state management (messages, loading, errors) |
| `src/components/chat/ChatContainer.tsx` | Main chat view, wires together message list and input |
| `src/components/chat/MessageBubble.tsx` | Renders individual messages with markdown and artifacts |
| `src/components/chat/InputArea.tsx` | User input with send button |
| `src/components/chat/MessageList.tsx` | Scrollable message list |
| `src/components/chat/ThinkingBubble.tsx` | Shows agent chain-of-thought steps |
| `src/components/chat/TypingIndicator.tsx` | Typing animation during agent processing |
| `src/components/visualization/ChartRenderer.tsx` | Renders Plotly charts from ChartConfig |
| `src/components/visualization/DataTable.tsx` | Renders tabular data |
| `src/components/visualization/ExportButton.tsx` | Export data as CSV/image |
| `src/components/visualization/SqlModal.tsx` | Modal showing formatted SQL with copy + navigation |
| `src/types/message.ts` | TypeScript types: Message, Artifact, StreamingEvent, etc. |
| `src/types/visualization.ts` | ChartConfig types, `chartConfigToPlotly()` converter |

### Building the Frontend

```bash
cd frontend
npm install
npx vite build --mode development
```

The build output goes to `frontend/dist/` and is deployed to S3. The single
environment variable `VITE_API_URL` controls where API calls are sent (the
Lambda Function URL).

### Chat and Streaming

The frontend communicates with the backend via the `AgentClient` class in
`src/services/agentClient.ts`. It supports two modes:

1. **Standard request/response** via `sendMessage()` -- sends a message and
   receives a complete response
2. **SSE streaming** via `sendMessageStreaming()` -- sends the same request but
   reads the response as a `ReadableStream`, parsing server-sent events for
   real-time updates

Streaming events include:
- `status` -- Progress updates (which agent is currently working, via `[TOOL_STATUS]` markers)
- `text` -- Incremental text output
- `complete` -- Final response with full data and artifacts
- `error` -- Error information

Streaming is **real-time** thanks to Lambda Web Adapter (LWA) running uvicorn
inside Lambda with `RESPONSE_STREAM` invoke mode. SSE events arrive
individually as they are generated, not batched.

### Visualization Pipeline

#### Charts

Charts flow through the system using text markers rather than tool calls:

1. The analyst agent generates chart specifications as JSON
2. The JSON is wrapped in `[CHART_CONFIG]{...}[/CHART_CONFIG]` text markers
3. The Lambda proxy extracts these markers using a regex, parses the JSON, and
   converts them into `Artifact` objects in the API response
4. The frontend receives artifacts with `type: "chart"` and renders them using
   `ChartRenderer.tsx`, which calls `chartConfigToPlotly()` to convert the
   internal `ChartConfig` format to Plotly trace/layout objects

The `ChartConfig` interface supports these chart types: `bar`, `line`, `pie`,
`scatter`, `heatmap`, and `histogram`.

#### SQL Artifacts

SQL queries are surfaced to the user for transparency:

1. The SQL agent wraps every executed query in `[SQL_QUERY]...[/SQL_QUERY]` markers
2. The Lambda proxy extracts these markers and creates `Artifact` objects with `type: "sql"`
3. The frontend renders SQL artifacts as a "View SQL" badge inline with the message
4. Clicking the badge opens `SqlModal.tsx`, which formats the SQL using `sql-formatter`
   and provides a copy-to-clipboard button and prev/next navigation for multiple queries

## Lambda Proxy

The Lambda proxy (`lambda_handler.py`) is a FastAPI application running via
**Lambda Web Adapter (LWA)** for real SSE streaming. It:

1. Accepts requests from the CloudFront distribution (via Lambda Function URL)
2. Validates Cognito JWT tokens from the `Authorization` header
3. Forwards the user message to the orchestrator agent via
   `boto3.client("bedrock-agent-runtime").invoke_agent_runtime()` with
   `RESPONSE_STREAM` for real-time streaming
4. Detects `[TOOL_STATUS:name]` markers in the stream and sends them as status SSE events
5. Extracts `[CHART_CONFIG]` markers from the response text and converts them
   to frontend-compatible chart artifact objects
6. Extracts `[SQL_QUERY]` markers from the response text and converts them
   to SQL artifact objects
7. Returns the response as real-time SSE (streaming) or JSON (non-streaming)

LWA works by:
- `run.sh` starts uvicorn on port 8080
- LWA's `/opt/bootstrap` proxies Lambda invocations to the uvicorn process
- The Function URL is configured with `InvokeMode: RESPONSE_STREAM`

The Lambda Function URL uses `AuthType: NONE` (auth is handled at the application
level via Cognito JWTs). This requires two Lambda permissions:
- `InvokeFunctionUrl`
- `InvokeFunction` with `InvokedViaFunctionUrl: true`

## Infrastructure

### CDK Stacks

The infrastructure is managed by AWS CDK (TypeScript) organized into three stacks:

| Stack | Directory | Purpose |
|-------|-----------|---------|
| `IlluminateBase-dev` | `cdk/lib/base/` | VPC, Cognito (LITE), S3, Secrets Manager, REGIONAL WAF, SSM parameters |
| `IlluminateAgentCore-dev` | `cdk/lib/agentcore/` | IAM role, Memory (STM), 5x Docker container runtimes (ECR) |
| `IlluminateAPI-dev` | `cdk/lib/api/` | Lambda + LWA + Function URL (`RESPONSE_STREAM`) |

A fourth stack (`cdk/lib/frontend/`) exists for S3 + CloudFront but is
currently deployed separately.

Deploy all stacks:
```bash
cd cdk && npx cdk deploy --all
```

The CDK app reads `.env` automatically -- no context flags needed.

### Request Flow

```
Browser
  |
  v
CloudFront Distribution
  |-- /* (default) ---------> S3 Bucket (frontend static files, via OAC)
  |-- /api/* ----------------> Lambda Function URL ---> Lambda Proxy (LWA)
  |-- /health --------------->                          |
                                                        v
                                              Orchestrator AgentCore
                                              (Docker container)
                                                        |
                                         +---------+----+----+---------+
                                         |         |         |         |
                                        SQL    Analyst    Writer   Validator
                                     (AgentCore container runtimes, A2A)
                                         |
                                         v
                                      Snowflake
```

### Key AWS Resources

- **Account**: 856599266077
- **Region**: us-east-1
- **IAM Role**: `illuminate-agent-role-dev`
- **Cognito User Pool**: `illuminate-users-dev`
- **Secrets Manager**: `illuminate/dev/snowflake` (Snowflake credentials)

## Important Patterns and Gotchas

### Agent Code Must Be Self-Contained

As described above, each agent is built into its own Docker container. No
cross-directory imports will work. Copy any shared code directly into each
agent's `a2a_server.py`.

### Chart and SQL Markers Instead of Tool Calls

Visualization data and SQL queries pass through the system as text markers
(`[CHART_CONFIG]...[/CHART_CONFIG]` and `[SQL_QUERY]...[/SQL_QUERY]`) rather
than structured tool call results. The Lambda proxy is responsible for
extracting and parsing these into artifacts.

### No Local Development Server

There is no local backend. Both development and production use AWS-hosted
infrastructure. The frontend build is deployed to S3 and served via CloudFront.
To test changes:
- **Agent changes**: Deploy with `npx cdk deploy IlluminateAgentCore-dev`
- **Frontend changes**: Build and upload to S3
- **Lambda changes**: Deploy with `npx cdk deploy IlluminateAPI-dev`

### Docker Required for Agent Deployment

CDK builds ARM64 Docker images locally via `DockerImageAsset`. Docker must be
running before deploying the AgentCore stack. On Apple Silicon Macs, ARM64
builds work natively. On x86 machines, QEMU emulation is required.

### AgentCore Error Codes

Common error codes when deploying or invoking agents:
- **424**: Container never starts (check dependencies, entry point)
- **502**: Application not responding (check port binding to 8080, health endpoint)
- **"init time exceeded"**: Slow initialization (reduce import time, defer heavy imports)

### Cognito Authentication

The frontend uses `amazon-cognito-identity-js` directly (not Amplify). The
`authService.ts` handles sign-in, sign-up, token refresh, and session management.
JWT tokens are attached to API requests via the `Authorization: Bearer <token>`
header.

### Environment Variables

Agent environment variables (including other agents' runtime ARNs) are set in
the CDK AgentCore stack and passed as environment variables to each container
runtime.

The frontend uses a single environment variable: `VITE_API_URL`, which is set at
build time and points to the Lambda Function URL.

## Troubleshooting

### Agent deployment fails

```bash
# Check CDK diff to see what changed
cd cdk && npx cdk diff IlluminateAgentCore-dev

# Check CloudWatch logs for the agent
aws logs tail /aws/bedrock-agentcore/illuminate_<agent>_dev --follow
```

### Agent returns 424 on invoke

The container failed to start. Common causes:
- Missing dependency in `requirements.txt`
- Import error in `a2a_server.py` (check for cross-agent imports)
- Dockerfile issue (check the shared `agents/Dockerfile`)

### Agent returns 502 on invoke

The container started but the app is not responding. Common causes:
- App not binding to port 8080
- Crash after startup (check CloudWatch logs)
- Missing environment variables

### Frontend API calls fail

- Verify `VITE_API_URL` is set correctly in the build
- Check that the Cognito token is valid and not expired
- Verify the Lambda Function URL permissions (both `InvokeFunctionUrl` and
  `InvokeFunction` with `InvokedViaFunctionUrl: true` are required)

### Charts not rendering

- Check that the agent response contains valid `[CHART_CONFIG]...[/CHART_CONFIG]`
  markers
- Verify the JSON inside the markers is valid and matches the `ChartConfig` type
- Check the browser console for Plotly rendering errors

### SQL artifacts not appearing

- Check that the SQL agent response contains `[SQL_QUERY]...[/SQL_QUERY]` markers
- Verify the Lambda proxy's regex is extracting them correctly
- Check the browser console for rendering errors in `SqlModal`
