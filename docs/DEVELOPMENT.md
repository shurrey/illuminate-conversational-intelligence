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
  - [CloudFormation Stacks](#cloudformation-stacks)
  - [Request Flow](#request-flow)
- [Important Patterns and Gotchas](#important-patterns-and-gotchas)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

Illuminate is a multi-agent conversational intelligence system that lets users query
Snowflake data using natural language. The system is composed of:

1. **Frontend** - React SPA served from S3 via CloudFront
2. **Lambda Proxy** - Thin FastAPI/Mangum handler that validates Cognito JWTs and
   forwards requests to the orchestrator
3. **Orchestrator Agent** - Coordinates specialist agents to fulfill user queries
4. **Specialist Agents** - SQL, Analyst, Writer, and Validator, each running as
   independent Bedrock AgentCore runtimes using the A2A (Agent-to-Agent) protocol

All agent code runs in AWS Bedrock AgentCore. There is no local development server
for the backend -- both dev and prod environments are AWS-hosted.

```
User -> CloudFront -> S3 (static files)
User -> CloudFront -> Lambda Function URL -> Lambda Proxy -> Orchestrator AgentCore
                                                                  |
                                                 +----------------+----------------+
                                                 |        |       |                |
                                               SQL    Analyst   Writer         Validator
                                            (AgentCore runtimes, A2A protocol)
```

## Project Structure

```
/
├── agents/
│   ├── orchestrator/        # Coordinates specialist agents
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── .bedrock_agentcore.yaml
│   ├── sql/                 # Generates and executes Snowflake SQL
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── .bedrock_agentcore.yaml
│   ├── analyst/             # Data analysis and interpretation
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── .bedrock_agentcore.yaml
│   ├── writer/              # Narrative report generation
│   │   ├── a2a_server.py
│   │   ├── requirements.txt
│   │   └── .bedrock_agentcore.yaml
│   └── validator/           # Result validation and quality checks
│       ├── a2a_server.py
│       ├── requirements.txt
│       └── .bedrock_agentcore.yaml
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── auth/            # Login, auth guards
│   │   │   ├── chat/            # ChatContainer, MessageBubble, InputArea, etc.
│   │   │   ├── layout/          # AppShell, Header, Sidebar
│   │   │   └── visualization/   # ChartRenderer, DataTable, ExportButton
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
├── infrastructure/
│   ├── cloudformation/          # CF templates (4-stack architecture)
│   └── scripts/                 # Deployment helper scripts
├── lambda_handler.py            # API proxy Lambda (FastAPI + Mangum)
└── docs/
    └── DEVELOPMENT.md           # This file
```

## Environment Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- AWS CLI configured with credentials for account 442606396405
- Bedrock AgentCore CLI (`agentcore`) installed
- Access to the `illuminate-agent-role-dev` IAM role

### Python Environment

```bash
# From the project root
source venv/bin/activate
```

The project uses a `venv` directory (not `.venv`).

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
environment variable must point to the deployed CloudFront URL for all API calls.

## Agent Development

### How Agents Work

Each agent is a self-contained Python application that:

1. Creates a **FastAPI** app
2. Instantiates a **Strands Agent** with `@tool`-decorated functions as capabilities
3. Mounts an **A2AServer** (from `strands-agents[a2a]`) onto the FastAPI app
4. Listens on **port 9000** (AgentCore convention)
5. Is deployed to **Bedrock AgentCore** as an A2A protocol runtime

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

2. Deploy the updated agent:
   ```bash
   cd agents/sql
   agentcore deploy
   ```

3. Test the deployed agent:
   ```bash
   agentcore invoke --runtime-id <runtime-id>
   ```

   The runtime ID can be found in `.bedrock_agentcore.yaml` under
   `bedrock_agentcore.agent_id`.

### Adding a New Agent

1. Create the agent directory:
   ```bash
   mkdir agents/myagent
   ```

2. Write `agents/myagent/a2a_server.py` following this pattern:

   ```python
   """
   MyAgent - Self-contained A2A server for AgentCore deployment.
   Zero `from agents.*` imports.
   """
   import json
   import os
   import sys
   from fastapi import FastAPI, Request
   from fastapi.responses import JSONResponse

   startup_log = []
   startup_error = None

   def log(msg):
       startup_log.append(msg)
       print(msg, file=sys.stderr, flush=True)

   try:
       log("Initializing MyAgent ...")
       from strands import Agent, tool
       from strands.models.bedrock import BedrockModel
       from strands_a2a import A2AServer

       @tool
       def my_capability(input_text: str) -> str:
           """Description of what this tool does."""
           # Implementation here
           return "result"

       model = BedrockModel(
           model_id=os.environ.get("MODEL_ID", "anthropic.claude-sonnet-4-6"),
           region_name=os.environ.get("AWS_REGION", "us-east-1"),
       )

       agent = Agent(
           model=model,
           tools=[my_capability],
           system_prompt="You are a specialist agent that ...",
       )

       a2a_server = A2AServer(agent=agent)
       app = FastAPI(title="MyAgent")
       a2a_server.mount(app)
       log("MyAgent initialized successfully")

   except Exception as e:
       startup_error = str(e)
       log(f"STARTUP ERROR: {e}")
       app = FastAPI(title="MyAgent-Error")

   @app.get("/health")
   async def health():
       return {"status": "ok" if not startup_error else "error",
               "startup_log": startup_log}

   if __name__ == "__main__":
       import uvicorn
       uvicorn.run(app, host="0.0.0.0", port=9000)
   ```

3. Write `agents/myagent/requirements.txt`:
   ```
   strands-agents[a2a]
   strands-agents-tools
   bedrock-agentcore
   fastapi>=0.115.0
   uvicorn>=0.32.0
   pydantic>=2.0.0
   boto3>=1.34.0
   ```

4. Create `.bedrock_agentcore.yaml` using `agentcore init` or by copying and
   modifying an existing one. Key fields to set:
   - `name`: Unique agent name (e.g., `illuminate_myagent_dev`)
   - `entrypoint`: Absolute path to `a2a_server.py`
   - `source_path`: Absolute path to the agent directory
   - `runtime_type`: `PYTHON_3_11`
   - `protocol_configuration.server_protocol`: `A2A`
   - `aws.execution_role`: `arn:aws:iam::442606396405:role/illuminate-agent-role-dev`

5. Deploy:
   ```bash
   cd agents/myagent
   agentcore deploy
   ```

6. Register the new agent in the orchestrator by adding a tool function to
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
   to the orchestrator's `.env.agentcore` file.

### Critical Constraint: Self-Contained Code

**Every `a2a_server.py` must be completely self-contained with zero cross-agent
imports.** This means:

- No `from agents.shared import ...`
- No `from agents.sql import ...`
- No relative imports referencing other agent directories

This is required because `agentcore deploy` flattens all source files into a zip
at the root level. Any import path like `agents.shared.utils` will not exist in
the deployed container.

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

Agent runtime ARNs are configured via environment variables loaded from
`.env.agentcore` files at startup.

## Frontend Development

### Tech Stack

- **React 18** with TypeScript
- **Vite** for build tooling
- **TailwindCSS** for styling
- **Plotly.js** (via react-plotly.js) for chart rendering
- **react-markdown** with remark-gfm for markdown rendering
- **amazon-cognito-identity-js** for Cognito authentication

### Key Source Files

| File | Purpose |
|------|---------|
| `src/App.tsx` | Root component, routing, auth state |
| `src/services/agentClient.ts` | API client; sends A2A messages, handles SSE streams |
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
CloudFront distribution URL).

### Chat and Streaming

The frontend communicates with the backend via the `AgentClient` class in
`src/services/agentClient.ts`. It supports two modes:

1. **Standard request/response** via `sendMessage()` -- sends a JSON-RPC 2.0
   message and receives a complete `AgentResponse`
2. **SSE streaming** via `sendMessageStreaming()` -- sends the same request but
   reads the response as a `ReadableStream`, parsing server-sent events for
   real-time updates

Streaming events include:
- `status` -- General status update
- `routing` -- Agent routing decision (which specialist to use)
- `thinking` -- Chain-of-thought content from the agent
- `tool_call` / `tool_result` -- Tool invocation details
- `text` -- Incremental text output
- `complete` -- Final response with full data
- `error` -- Error information

Note: The Lambda proxy runs in BUFFERED mode (Python Lambda does not support
`RESPONSE_STREAM`), so SSE events arrive in batches rather than truly real-time.

### Visualization Pipeline

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

## Lambda Proxy

The Lambda proxy (`lambda_handler.py`) is a thin FastAPI application wrapped with
Mangum for Lambda compatibility. It:

1. Accepts requests from the CloudFront distribution (via Lambda Function URL)
2. Validates Cognito JWT tokens from the `Authorization` header
3. Forwards the user message to the orchestrator agent via
   `boto3.client("bedrock-agent-runtime").invoke_agent_runtime()`
4. Extracts `[CHART_CONFIG]` markers from the response text and converts them
   to frontend-compatible artifact objects
5. Returns the response as JSON (or SSE for streaming endpoints)

The Lambda Function URL uses `AuthType: NONE` (auth is handled at the application
level via Cognito JWTs). This requires two Lambda permissions:
- `InvokeFunctionUrl`
- `InvokeFunction` with `InvokedViaFunctionUrl: true`

## Infrastructure

### CloudFormation Stacks

The infrastructure is organized into four CloudFormation stacks, deployed in order:

| Stack | Template | Purpose |
|-------|----------|---------|
| 1 | `1-base-infrastructure.yaml` | VPC, Cognito user pool, REGIONAL WAF, Secrets Manager, S3 buckets |
| 2 | `2-agentcore.yaml` | AgentCore Gateway, Memory, agent runtime definitions |
| 3 | `3-api-gateway.yaml` | Lambda proxy function + Function URL (API Gateway has been removed) |
| 4 | `4-frontend.yaml` | S3 bucket (OAC), CloudFront distribution (API origin + GLOBAL WAF + SPA routing) |

### Request Flow

```
Browser
  |
  v
CloudFront Distribution
  |-- /* (default) ---------> S3 Bucket (frontend static files, via OAC)
  |-- /api/* ----------------> Lambda Function URL ---> Lambda Proxy
  |-- /health --------------->                          |
                                                        v
                                              Orchestrator AgentCore
                                                        |
                                         +---------+----+----+---------+
                                         |         |         |         |
                                        SQL    Analyst    Writer   Validator
                                     (AgentCore runtimes, A2A protocol)
                                         |
                                         v
                                      Snowflake
```

### Key AWS Resources

- **Account**: 442606396405
- **Region**: us-east-1
- **IAM Role**: `illuminate-agent-role-dev`
- **S3 (build sources)**: `bedrock-agentcore-codebuild-sources-442606396405-us-east-1`
- **Cognito User Pool**: `illuminate-users-dev` (ID: `us-east-1_ZWs8MEKzt`)
- **Secrets Manager**: `illuminate/dev/snowflake` (Snowflake credentials)

## Important Patterns and Gotchas

### Agent Code Must Be Self-Contained

As described above, `agentcore deploy` flattens all files to the zip root. No
cross-directory imports will work. Copy any shared code directly into each
agent's `a2a_server.py`.

### Chart Markers Instead of Tool Calls

Visualization data passes through the system as text markers
(`[CHART_CONFIG]...[/CHART_CONFIG]`) rather than structured tool call results.
The Lambda proxy is responsible for extracting and parsing these into artifacts.

### No Local Development Server

There is no local backend. Both development and production use AWS-hosted
infrastructure. The frontend build is deployed to S3 and served via CloudFront.
To test changes:
- **Agent changes**: Deploy with `agentcore deploy` and test with `agentcore invoke`
- **Frontend changes**: Build and upload to S3
- **Lambda changes**: Package and deploy the Lambda function

### Lambda Buffered Mode

Python Lambda does not support `RESPONSE_STREAM` invoke mode. The Lambda proxy
uses `BUFFERED` mode, which means SSE events are accumulated and sent as a batch
rather than streamed in real-time. The frontend handles this gracefully.

### AgentCore Error Codes

Common error codes when deploying or invoking agents:
- **424**: Container never starts (check dependencies, entry point)
- **502**: Application not responding (check port binding, health endpoint)
- **"init time exceeded"**: Slow initialization (reduce import time, defer heavy imports)

### Cognito Authentication

The frontend uses `amazon-cognito-identity-js` directly (not Amplify). The
`authService.ts` handles sign-in, sign-up, token refresh, and session management.
JWT tokens are attached to API requests via the `Authorization: Bearer <token>`
header.

### Environment Variables

Agent environment variables (including other agents' runtime ARNs) are stored in
`.env.agentcore` files in each agent directory. These are loaded at startup by
each `a2a_server.py`.

The frontend uses a single environment variable: `VITE_API_URL`, which is set at
build time and points to the CloudFront distribution URL.

## Troubleshooting

### Agent deployment fails

```bash
# Check the deployment logs
agentcore deploy --verbose

# Verify the .bedrock_agentcore.yaml is valid
cat agents/<name>/.bedrock_agentcore.yaml
```

### Agent returns 424 on invoke

The container failed to start. Common causes:
- Missing dependency in `requirements.txt`
- Import error in `a2a_server.py` (check for cross-agent imports)
- Invalid entry point path in `.bedrock_agentcore.yaml`

### Agent returns 502 on invoke

The container started but the app is not responding. Common causes:
- App not binding to port 9000
- Crash after startup (check the `/health` endpoint output for `startup_error`)
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
