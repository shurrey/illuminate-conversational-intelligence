# Illuminate Conversational Intelligence -- Architecture

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Agent Architecture](#2-agent-architecture)
3. [Request Flow](#3-request-flow)
4. [Authentication and Security](#4-authentication-and-security)
5. [Data Flow for Chart and Visualization Generation](#5-data-flow-for-chart-and-visualization-generation)
6. [SQL Transparency](#6-sql-transparency)
7. [Real-Time Tool Status](#7-real-time-tool-status)
8. [Conversation Context Management](#8-conversation-context-management)
9. [Infrastructure](#9-infrastructure)
10. [Container Deployment](#10-container-deployment)
11. [Design Decisions](#11-design-decisions)

---

## 1. System Overview

Illuminate Conversational Intelligence (ICI) is a multi-agent system that enables educational administrators to query, analyze, and visualize institutional data through natural language. Users ask questions in plain English; the system translates those into SQL queries against a Snowflake data warehouse, analyzes the results, writes a polished response, validates it for FERPA compliance, and returns the answer -- optionally with interactive charts.

All agent logic runs on **AWS Bedrock AgentCore** as self-contained containerized A2A (Agent-to-Agent) protocol runtimes. A thin Lambda proxy sits between the frontend and the orchestrator. The frontend is a React SPA served from S3 via CloudFront.

### High-Level Architecture

```
                           +---------------------------+
                           |     React SPA (Vite)      |
                           |  Cognito Auth, Plotly.js  |
                           |  sql-formatter            |
                           +-------------|-------------+
                                         |
                    Static assets        | API calls
                    via CloudFront       | (HTTPS, JWT)
                         |               |
            +------------|---------------|------------------+
            |            v               v                  |
            |   +----------------+   +------------------+  |
            |   |  S3 Bucket     |   | Lambda Fn URL    |  |
            |   |  (OAC, priv.)  |   | (FastAPI + LWA)  |  |
            |   +----------------+   +--------|--------+   |
            |                                 |            |
            |        CloudFront (WAF)         |            |
            +---------------------------------|------------+
                                              |
                           boto3 invoke_agent_runtime (SigV4)
                                              |
                                              v
                    +--------------------------------------------------+
                    |          AWS Bedrock AgentCore                    |
                    |          (Docker containers, ARM64)               |
                    |                                                   |
                    |   +------------------------------------------+   |
                    |   |         Orchestrator Agent                |   |
                    |   |  (Sonnet 4.6, Strands SDK, A2A Server)   |   |
                    |   |  STM middleware, specialist routing       |   |
                    |   +-----|---------|---------|-----------|-----+   |
                    |         |         |         |           |         |
                    |   invoke_agent_runtime (SigV4, A2A JSON-RPC)     |
                    |         |         |         |           |         |
                    |         v         v         v           v         |
                    |   +---------+ +---------+ +--------+ +---------+ |
                    |   |   SQL   | | Analyst | | Writer | |Validator| |
                    |   |Sonnet4.6| |Sonnet4.6| |Snnt 4.6| |Snnt 4.6| |
                    |   +---|-----+ +---------+ +--------+ +---------+ |
                    |       |                                           |
                    +-------|-------------------------------------------+
                            |
                            v
                    +----------------+
                    |   Snowflake    |
                    |  Data Warehouse|
                    |  (CDM_LMS)     |
                    +----------------+
```

### Key Technologies

| Layer          | Technology                                       |
|----------------|--------------------------------------------------|
| Frontend       | React 18, TypeScript, Vite, TailwindCSS, Plotly, sql-formatter |
| Auth           | Amazon Cognito (User Pool + SRP auth, LITE tier) |
| API Proxy      | AWS Lambda (Python 3.13, FastAPI, Lambda Web Adapter) |
| Agent Runtime  | AWS Bedrock AgentCore, Strands Agents SDK        |
| Agent Protocol | A2A (Agent-to-Agent) over JSON-RPC 2.0           |
| Models         | Claude Sonnet 4.6 (via Bedrock cross-region inference) |
| Data Store     | Snowflake (snowflake-connector-python)           |
| Secrets        | AWS Secrets Manager                               |
| CDN / WAF      | CloudFront, WAFv2 (CLOUDFRONT scope)             |
| IaC            | AWS CDK (TypeScript, 3 stacks: Base, AgentCore, API) |

---

## 2. Agent Architecture

The system comprises five agents, each deployed as an independent Bedrock AgentCore container runtime. Every agent is a self-contained `a2a_server.py` file with zero cross-module imports (`from agents.*`), which is a hard requirement for containerized deployment. Each agent directory contains a `Dockerfile` symlink pointing to the shared `agents/Dockerfile`.

Each agent follows the same structural pattern:

1. Import the Strands SDK (`Agent`, `tool`, `BedrockModel`) and `strands_a2a.a2a` (`build_a2a_app`).
2. Define domain-specific `@tool` functions.
3. Create a `strands.Agent` with a system prompt and tools.
4. Build the ASGI app via `build_a2a_app(agent)`.
5. Listen on **port 8080** (LWA convention).

### 2.1 Orchestrator Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/orchestrator/a2a_server.py`           |
| Model       | Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) |
| Role        | Central coordinator; routes to specialists     |
| Tools       | `query_database`, `analyze_data`, `write_response`, `validate_response` |

The orchestrator is the only agent the Lambda proxy communicates with. It receives a user's natural language question and determines which specialist agents to invoke and in what order. Its four tools are thin wrappers that call `invoke_specialist()`, which sends an A2A JSON-RPC `message/send` request to the target agent's runtime via `boto3.client('bedrock-agent-runtime').invoke_agent_runtime()`.

The orchestrator also hosts a **pure ASGI context enrichment middleware** that intercepts incoming A2A `message/send` requests and routes `contextId` to STM (Short-Term Memory) sessions via `AgentCoreMemorySessionManager`. See Section 8 for details.

The system prompt includes `[TOOL_STATUS:agent_name]` markers that the Lambda proxy extracts for real-time frontend status updates. See Section 7.

The system prompt instructs the orchestrator to follow a standard pipeline for data questions:

1. `query_database` -- get data from Snowflake
2. `analyze_data` -- interpret results
3. `write_response` -- craft the user-facing answer
4. `validate_response` -- FERPA compliance check
5. Return the validated response

For visualization requests, the orchestrator embeds `[CHART_CONFIG]...[/CHART_CONFIG]` text markers in its response. See Section 5.

### 2.2 SQL Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/sql/a2a_server.py`                    |
| Model       | Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) |
| Role        | Generate and execute SQL against Snowflake     |
| Tools       | `list_objects`, `describe_object`, `run_snowflake_query` |

The SQL agent connects directly to Snowflake via `snowflake-connector-python`. Credentials are loaded from AWS Secrets Manager (`illuminate/dev/snowflake`) at startup. The connection is lazily initialized and reused across requests.

Key safeguards:
- Only `SELECT`, `WITH`, and `SHOW` statements are allowed; the `run_snowflake_query` tool rejects anything else.
- Fully qualified table names are required (`DATABASE.CDM_LMS.TABLE_NAME`).
- The system prompt enforces FERPA rules: aggregate data only, minimum 5 individuals per group, `PERSON_ID` used only for JOINs.
- Default `LIMIT 100` to prevent unbounded result sets.
- Every executed SQL query is wrapped in `[SQL_QUERY]...[/SQL_QUERY]` markers for transparency. See Section 6.

### 2.3 Analyst Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/analyst/a2a_server.py`                |
| Model       | Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) |
| Role        | Interpret data; identify trends and patterns   |
| Tools       | `analyze_data`                                |

The analyst receives query results (typically markdown tables) and the original user question. It produces structured analysis with:
- A one-sentence summary
- 3-5 key insights with specific numbers
- Trend identification
- 2-3 actionable recommendations
- Educational context (e.g., course completion benchmarks)

### 2.4 Writer Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/writer/a2a_server.py`                 |
| Model       | Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) |
| Role        | Craft clear, user-facing natural language      |
| Tools       | `write_response`                              |

The writer transforms raw data and analysis into conversational prose for educational administrators. It formats data as markdown tables for small datasets and summaries for larger ones, and ends each response with 2-3 suggested follow-up questions.

### 2.5 Validator Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/validator/a2a_server.py`              |
| Model       | Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) |
| Role        | FERPA compliance, PII detection, accuracy      |
| Tools       | `validate_response`                           |

The validator implements a two-tier compliance check:

**Tier 1 -- Rule-based PII detection (regex):**
Runs before the LLM sees the response. Patterns checked:
- SSNs (`\b\d{3}-\d{2}-\d{4}\b` and `\b\d{9}\b`)
- Email addresses
- Phone numbers (10-digit and parenthesized formats)

**Tier 2 -- LLM-as-a-Judge:**
The Sonnet 4.6 model evaluates the response for:
- SQL safety (if SQL is visible)
- Data plausibility (percentages sum to ~100%, counts are reasonable)
- FERPA compliance (no individual student names in grade contexts, aggregation minimums)
- Response quality (actually answers the user's question)

The validator returns a structured assessment: `passed`, `failed`, `warning`, or `needs_review`, along with a confidence score (0.0-1.0). If validation fails, the orchestrator is instructed to revise and re-validate.

---

## 3. Request Flow

A complete request from the user's browser to the final response follows this path:

### Step-by-Step

```
Browser                Lambda Fn URL        AgentCore Orchestrator       Specialists
  |                         |                         |                       |
  |  1. POST /api/chat/stream                         |                       |
  |    {message, context_id}|                         |                       |
  |    Authorization: Bearer <JWT>                    |                       |
  |------------------------>|                         |                       |
  |                         |                         |                       |
  |  2. Validate JWT        |                         |                       |
  |    (Cognito JWKS)       |                         |                       |
  |                         |                         |                       |
  |  3. Build A2A JSON-RPC  |                         |                       |
  |    message/send payload |                         |                       |
  |    + runtimeSessionId   |                         |                       |
  |                         |                         |                       |
  |                         | 4. invoke_agent_runtime |                       |
  |                         |    (boto3, SigV4,       |                       |
  |                         |     RESPONSE_STREAM)    |                       |
  |                         |------------------------>|                       |
  |                         |                         |                       |
  |                         |                         | 5. ASGI middleware    |
  |                         |                         |    routes contextId   |
  |                         |                         |    to STM session     |
  |                         |                         |                       |
  |                         |                         | 6. Strands Agent      |
  |                         |                         |    reasons, selects   |
  |                         |                         |    tools              |
  |                         |                         |                       |
  |                         |                         | 7. query_database --->| SQL Agent
  |  SSE: [TOOL_STATUS:sql] |                         |    (invoke_agent_     | Snowflake query
  |<------------------------|                         |     runtime, SigV4)  | returns markdown
  |                         |                         |<------- results -----|
  |                         |                         |                       |
  |                         |                         | 8. analyze_data ----->| Analyst Agent
  |  SSE: [TOOL_STATUS:     |                         |                       |
  |        analyst]         |                         |<------- insights ----|
  |<------------------------|                         |                       |
  |                         |                         |                       |
  |                         |                         | 9. write_response --->| Writer Agent
  |<------------------------|                         |<------- prose -------|
  |                         |                         |                       |
  |                         |                         | 10. validate_response>| Validator Agent
  |<------------------------|                         |<------- pass/fail ---|
  |                         |                         |                       |
  |                         | 11. A2A response        |                       |
  |                         |    (text w/ optional     |                       |
  |                         |     [CHART_CONFIG],      |                       |
  |                         |     [SQL_QUERY])         |                       |
  |                         |<------------------------|                       |
  |                         |                         |                       |
  |  12. Extract chart      |                         |                       |
  |    configs + SQL from   |                         |                       |
  |    text markers, build  |                         |                       |
  |    artifact objects     |                         |                       |
  |                         |                         |                       |
  |  13. SSE: data: {type:  |                         |                       |
  |    "complete", data:    |                         |                       |
  |    {text, artifacts,    |                         |                       |
  |     contextId}}         |                         |                       |
  |<------------------------|                         |                       |
  |                         |                         |                       |
  | 14. Render text +       |                         |                       |
  |     Plotly chart +      |                         |                       |
  |     SQL badge           |                         |                       |
```

### Detailed Steps

1. **Browser sends request.** The frontend's `AgentClient.sendMessageStreaming()` POSTs to `/api/chat/stream` with a JSON body containing the message text and a `context_id` (for conversation continuity). The `Authorization: Bearer <id_token>` header carries the Cognito JWT.

2. **Lambda validates JWT.** The Lambda handler (`lambda_handler.py`) fetches the Cognito JWKS (cached for 1 hour), locates the signing key by `kid`, and verifies the RS256 signature, audience, and issuer claims. Invalid tokens receive HTTP 401.

3. **Lambda builds A2A payload.** The message is wrapped in a JSON-RPC 2.0 `message/send` request with a `messageId`, `contextId`, and a `parts` array containing a single text part. The `runtimeSessionId` is set to the `context_id` for STM routing.

4. **Lambda invokes the orchestrator.** Calls `boto3.client('bedrock-agent-runtime').invoke_agent_runtime()` with the orchestrator's runtime ARN and `RESPONSE_STREAM` for real streaming. Authentication is SigV4, handled automatically by boto3 using the Lambda's execution role.

5. **Orchestrator middleware routes to STM.** The pure ASGI middleware intercepts the request and routes the `contextId` to an STM session via `AgentCoreMemorySessionManager`, providing conversation history to the agent.

6. **Orchestrator agent reasons.** The Strands Agent (Sonnet 4.6) processes the message with STM context, reads the system prompt, and decides which tools to invoke.

7. **SQL Agent queries Snowflake.** The orchestrator calls `query_database()`, which invokes the SQL Agent via `invoke_agent_runtime()`. The SQL Agent generates a SQL query, executes it via `snowflake-connector-python`, and returns results as a markdown table with `[SQL_QUERY]` markers.

8. **Analyst Agent interprets results.** The orchestrator calls `analyze_data()`, forwarding query results and the original question. The Analyst Agent returns structured insights.

9. **Writer Agent crafts the response.** The orchestrator calls `write_response()`, forwarding data, analysis, and the original question. The Writer Agent returns polished prose.

10. **Validator Agent checks compliance.** The orchestrator calls `validate_response()`, forwarding the full response. The Validator Agent runs regex PII checks, then uses Sonnet 4.6 as an LLM judge. If validation fails, the orchestrator can revise and re-validate.

11. **Orchestrator returns the response.** The A2A response flows back through the AgentCore runtime to the Lambda proxy. The response text may contain `[CHART_CONFIG]...[/CHART_CONFIG]` and `[SQL_QUERY]...[/SQL_QUERY]` markers.

12. **Lambda extracts artifacts.** Regex patterns find all `[CHART_CONFIG]` and `[SQL_QUERY]` blocks, parse them, create frontend-compatible artifact objects (chart or sql type), strip the markers from the text, and clean up whitespace.

13. **Lambda streams SSE response.** The response is sent as a real-time Server-Sent Events stream via Lambda Web Adapter. The final event has `type: "complete"` with `data.text` (cleaned markdown), `data.artifacts` (chart and SQL objects), and `data.contextId`.

14. **Frontend renders the response.** `MessageBubble` displays the markdown text. If chart artifacts are present, `ChartRenderer` lazy-loads Plotly.js and renders interactive charts. If SQL artifacts are present, a "View SQL" badge is shown that opens `SqlModal` with formatted SQL, copy button, and prev/next navigation.

---

## 4. Authentication and Security

### 4.1 User Authentication (Cognito)

```
Browser                         Cognito                      Lambda
  |                                |                           |
  | 1. authenticateUser(SRP)       |                           |
  |------------------------------->|                           |
  |                                |                           |
  | 2. CognitoUserSession          |                           |
  |   {idToken, accessToken,       |                           |
  |    refreshToken}               |                           |
  |<-------------------------------|                           |
  |                                                            |
  | 3. API call + Authorization: Bearer <idToken>              |
  |------------------------------------------------------->   |
  |                                                            |
  |                          4. Verify JWT signature (RS256)   |
  |                             against JWKS from Cognito      |
  |                             Check: iss, aud, exp           |
  |                                                            |
  |                          5. Extract user claims            |
  |                             (sub, email, name)             |
```

- **User Pool:** `illuminate-users-{env}` with email-based sign-in, Cognito LITE tier.
- **Password Policy:** Minimum 12 characters, requires upper + lower + number + symbol.
- **Auth Flows:** SRP, User Password, and Refresh Token.
- **Frontend Library:** `amazon-cognito-identity-js` handles SRP authentication directly against Cognito (no hosted UI).
- **Token Storage:** The frontend stores the auth state (user, token) in `localStorage` under the key `illuminate_auth`.
- **JWT Validation:** The Lambda validates the Cognito ID token on every request. JWKS is fetched from `https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json` and cached for 1 hour.
- **Initial User Creation:** CDK creates the first user via `AwsCustomResource` on initial deployment, using the `INITIAL_USER_EMAIL` and `INITIAL_USER_PASSWORD` values from `.env`.

### 4.2 Service-to-Service Authentication (SigV4)

All inter-service communication uses AWS IAM SigV4 authentication:

- **Lambda to Orchestrator:** The Lambda's execution role has `bedrock:InvokeAgentRuntime` permission scoped to the orchestrator runtime.
- **Orchestrator to Specialists:** The AgentCore runtime role has `bedrock:InvokeAgentRuntime` permission scoped to all `illuminate_*` runtimes.
- **Orchestrator to Bedrock Models:** The runtime role has `bedrock:InvokeModel` and `bedrock:ConverseStream` permissions for Claude models.
- **SQL Agent to Secrets Manager:** The runtime role has `secretsmanager:GetSecretValue` for the Snowflake secret.
- **Memory Access:** The runtime role has `bedrock:RetrieveMemorySession` and `bedrock:CreateMemorySession` for STM.

No API keys, shared secrets, or long-lived credentials are used between services. All authentication is handled by IAM role assumption and SigV4 request signing.

### 4.3 WAF (Web Application Firewall)

Two WAF WebACLs protect the system:

| WAF                  | Scope       | Attached To      | Rules                                        |
|----------------------|-------------|------------------|----------------------------------------------|
| `illuminate-waf`     | REGIONAL    | (base stack)     | Rate limiting, Common Rules, SQLi, Bad Inputs |
| `illuminate-cf-waf`  | CLOUDFRONT  | CloudFront dist. | Rate limiting, Common Rules, SQLi, Bad Inputs |

CloudFront requires a CLOUDFRONT-scoped WAF (deployed in `us-east-1`), so the base stack's REGIONAL WAF cannot be reused. Both WAFs apply:

- **Rate limiting:** 2000 req/5min per IP (dev), 1000 req/5min (prod).
- **AWS Managed Rules:** Common Rule Set, SQL Injection Rule Set, Known Bad Inputs Rule Set.
- **SizeRestrictions_BODY excluded** on the CloudFront WAF to allow large agent request/response bodies.

### 4.4 CORS

CORS is handled by **FastAPI CORSMiddleware** in the Lambda handler, not by the Lambda Function URL configuration (to avoid duplicate headers). Allowed origins are configured via the `ALLOWED_ORIGINS` environment variable:

- **Dev:** `http://localhost:3000`, `http://localhost:5173`, plus the CloudFront domain.
- **Prod:** `https://illuminate.anthology.com`, plus the CloudFront domain.

### 4.5 Network Security

- The Lambda function runs in **private subnets** within the VPC (`10.0.11.0/24`, `10.0.12.0/24`).
- Outbound internet access (for Cognito JWKS, AgentCore API) is via a **NAT Gateway** in a public subnet.
- A **security group** restricts inbound traffic to HTTPS (port 443) from within the same security group.
- The S3 frontend bucket is fully private; access is exclusively via **CloudFront Origin Access Control (OAC)**.

### 4.6 FERPA Compliance

FERPA (Family Educational Rights and Privacy Act) compliance is enforced at multiple layers:

1. **SQL Agent system prompt:** Instructs the model to never return individual student PII and to aggregate with minimum group sizes of 5.
2. **Validator Agent regex patterns:** Detects SSNs, emails, and phone numbers in response text before the LLM even sees it.
3. **Validator Agent LLM-as-a-Judge:** Sonnet 4.6 evaluates the full response for individual student name exposure, data plausibility, and aggregation compliance.
4. **Orchestrator pipeline:** If the validator returns `failed`, the orchestrator is instructed to revise and re-submit.

---

## 5. Data Flow for Chart and Visualization Generation

Charts are generated through a text-marker protocol that bridges the LLM's text output and the frontend's Plotly rendering.

### Why Text Markers?

LLMs produce text. Rather than introducing a separate structured output channel (which would require custom A2A protocol extensions and complex parsing at every layer), the system embeds chart specifications as JSON inside text markers. This approach:

- Works unchanged through all A2A intermediaries.
- Requires no modifications to the Strands SDK or A2A protocol.
- Is easy for the LLM to produce (it is writing JSON inside delimiters in its natural text output).
- Allows a single response to contain both prose and multiple charts.

### Marker Format

```
[CHART_CONFIG]
{
  "chart_type": "bar",
  "title": "Enrollment by Department",
  "x_axis": "department",
  "y_axis": "enrollment",
  "x_label": "Department",
  "y_label": "Student Count",
  "data": [
    {"department": "Computer Science", "enrollment": 342},
    {"department": "Mathematics", "enrollment": 218},
    {"department": "English", "enrollment": 195}
  ]
}
[/CHART_CONFIG]
```

Supported `chart_type` values: `bar`, `line`, `pie`, `scatter`, `histogram`.

### End-to-End Flow

```
1. User: "Show me enrollment by department as a bar chart"
          |
2. Orchestrator calls SQL Agent
   SQL Agent executes: SELECT department, COUNT(*) as enrollment
                       FROM DATABASE.CDM_LMS.ENROLLMENTS
                       GROUP BY department
   Returns markdown table with real data
          |
3. Orchestrator includes [CHART_CONFIG] block in its response text
   with actual data from the SQL results (not placeholder data)
          |
4. A2A response travels back through AgentCore to Lambda
          |
5. Lambda's extract_chart_configs() function:
   a. Regex finds all [CHART_CONFIG]...[/CHART_CONFIG] blocks
   b. Parses JSON inside each block
   c. Validates chart_type against allowed list
   d. Creates chart artifact objects:
      {id: uuid, type: "chart", title: "...", data: {chart_type, data, ...}}
   e. Strips markers from text, cleans up whitespace
          |
6. Lambda sends SSE event:
   data: {"type": "complete", "data": {"text": "...", "artifacts": [...]}}
          |
7. Frontend MessageBubble detects artifacts with type "chart"
   ChartRenderer lazy-loads react-plotly.js
   chartConfigToPlotly() converts the config to Plotly trace/layout format
   Plotly renders an interactive chart (zoom, pan, hover, export)
```

### Frontend Chart Types

The `chartConfigToPlotly()` function in `types/visualization.ts` maps each `chart_type` to a Plotly trace type:

| ICI chart_type | Plotly type | Notes                              |
|----------------|-------------|------------------------------------|
| `bar`          | `bar`       | x/y from data keys                |
| `line`         | `scatter`   | mode: `lines+markers`             |
| `pie`          | `pie`       | labels from x_axis, values from y_axis |
| `scatter`      | `scatter`   | mode: `markers`                   |
| `histogram`    | `histogram` | x from data keys                  |

---

## 6. SQL Transparency

Every SQL query executed by the SQL Agent is surfaced to the user as a navigable artifact, enabling full transparency into what queries were run.

### Marker Format

```
[SQL_QUERY]SELECT department, COUNT(*) as enrollment FROM DATABASE.CDM_LMS.ENROLLMENTS GROUP BY department[/SQL_QUERY]
```

### End-to-End Flow

1. The SQL Agent wraps every executed query in `[SQL_QUERY]...[/SQL_QUERY]` markers within its response text.
2. The Lambda proxy extracts these markers using a regex, creates artifact objects with `type: "sql"`.
3. The frontend renders each SQL artifact as a "View SQL" badge inline with the message.
4. Clicking the badge opens `SqlModal`, which displays the SQL formatted with `sql-formatter`.
5. The modal includes a copy-to-clipboard button and prev/next navigation when multiple SQL queries are present.

---

## 7. Real-Time Tool Status

The system provides real-time status updates to the frontend as the orchestrator invokes each specialist agent. This gives users visibility into which step of the pipeline is currently executing.

### How It Works

1. The orchestrator's system prompt includes `[TOOL_STATUS:agent_name]` markers that the LLM emits before calling each specialist tool.
2. As the Lambda proxy streams the response from AgentCore, it detects these markers in the SSE stream.
3. Each detected marker is sent to the frontend as a `status` SSE event (e.g., `{"type": "status", "message": "Querying database..."}`).
4. The markers are stripped from the final response text.

This approach requires no custom tool-call instrumentation -- the LLM naturally emits the markers as part of its reasoning, and the Lambda extracts them during streaming.

---

## 8. Conversation Context Management

Multi-turn conversations are managed by AgentCore's **Short-Term Memory (STM)** service, accessed via the `AgentCoreMemorySessionManager` from the Strands SDK.

### How It Works

The orchestrator uses a **pure ASGI middleware** (not `BaseHTTPMiddleware`, which breaks SSE streaming) that intercepts incoming A2A `message/send` requests:

1. **Extract contextId** from the A2A message params.
2. **Map to STM session** via the `runtimeSessionId` parameter passed through `invoke_agent_runtime()`.
3. **AgentCoreMemorySessionManager** handles session creation, retrieval, and persistence automatically.
4. The Strands Agent receives the full conversation history from STM, enabling multi-turn context.

### Why STM Over In-Memory Storage?

The system originally used an in-memory dictionary on the orchestrator container for conversation history. This was replaced with AgentCore STM because:

- **Persistence:** STM survives container restarts and scaling events. In-memory storage was lost on restart.
- **Managed service:** No custom truncation or memory management code needed.
- **Session routing:** The `runtimeSessionId` parameter automatically routes requests to the correct STM session.

### STM Configuration

- **Memory resource** is provisioned by CDK in the AgentCore stack.
- **Event expiry:** 24 hours (configurable).
- **Session ID:** Uses the frontend's `context_id` (UUID per conversation), passed as `runtimeSessionId` in the `invoke_agent_runtime()` call.

---

## 9. Infrastructure

The system is deployed via **AWS CDK** (TypeScript) organized into three stacks. The CDK app reads configuration from `.env` automatically.

### CDK Stacks

```
+-----------------------------------+
| IlluminateBase-{env}              |
| VPC, Cognito (LITE), S3, Secrets, |
| WAF, SSM discovery parameters     |
+-------------|---------------------+
              |
     SSM parameters, Cognito, VPC
              |
+-------------|---------------------+
| IlluminateAgentCore-{env}         |
| IAM role, Memory (STM),          |
| 5x Docker container runtimes     |
| (DockerImageAsset -> ECR)         |
+-------------|---------------------+
              |
     Orchestrator ARN via SSM
              |
+-------------|---------------------+
| IlluminateAPI-{env}               |
| Lambda + LWA + Function URL      |
| (RESPONSE_STREAM invoke mode)     |
+-----------------------------------+
```

A fourth stack (`IlluminateFrontend-{env}`) for S3 + CloudFront exists in `cdk/lib/frontend/` but is currently deployed separately via the legacy shell scripts.

### SSM Service Discovery

All stacks communicate via SSM Parameter Store. Key parameters:

| Parameter | Set By | Used By |
|-----------|--------|---------|
| `/illuminate/{env}/cognito-pool-id` | Base | API, Frontend |
| `/illuminate/{env}/cognito-client-id` | Base | API, Frontend |
| `/illuminate/{env}/api-url` | API | Frontend |
| `/illuminate/{env}/orchestrator-arn` | AgentCore | API |
| `/illuminate/{env}/memory-id` | AgentCore | API |
| `/illuminate/{env}/sql-arn` | AgentCore | Orchestrator |
| `/illuminate/{env}/analyst-arn` | AgentCore | Orchestrator |
| `/illuminate/{env}/writer-arn` | AgentCore | Orchestrator |
| `/illuminate/{env}/validator-arn` | AgentCore | Orchestrator |

### Lambda Web Adapter (LWA)

The Lambda proxy uses **Lambda Web Adapter** instead of Mangum. LWA runs uvicorn inside the Lambda container, enabling real SSE streaming via `RESPONSE_STREAM` invoke mode on the Function URL.

How it works:
1. `run.sh` starts uvicorn on port 8080.
2. LWA's `/opt/bootstrap` proxies Lambda invocations to the uvicorn process.
3. The Function URL is configured with `InvokeMode: RESPONSE_STREAM`.
4. SSE events are streamed to the client in real time (not batched).

This replaces the previous Mangum-based approach, which required `BUFFERED` invoke mode and delivered SSE events in batches rather than in real time.

### Legacy Infrastructure

The `infrastructure/` directory contains the original CloudFormation templates and shell scripts:
- `infrastructure/cloudformation/` -- 4 YAML stacks (superseded by CDK)
- `infrastructure/scripts/` -- Deployment shell scripts

These are still functional but superseded by CDK for all stacks except the frontend, which is still deployed via `infrastructure/scripts/deploy-frontend.sh`.

---

## 10. Container Deployment

Agents are deployed as Docker containers to Bedrock AgentCore via CDK's `DockerImageAsset`.

### Shared Dockerfile

All five agents share a single `agents/Dockerfile`:

- **Base image:** Python 3.13 slim (bookworm)
- **Package manager:** uv (for fast dependency installation)
- **Architecture:** ARM64
- **User:** Non-root (`appuser`)
- **Port:** 8080

Each agent directory contains a `Dockerfile` symlink pointing to `../Dockerfile`. CDK uses `DockerImageAsset` to build each agent's image (with the agent directory as context), push it to ECR, and reference it in a `CfnRuntime` resource.

### Build Process

When you run `npx cdk deploy IlluminateAgentCore-{env}`:

1. CDK detects each `DockerImageAsset` and builds the Docker image locally.
2. Images are tagged and pushed to an ECR repository managed by CDK.
3. `CfnRuntime` resources reference the ECR image URI.
4. AgentCore pulls the image and starts the container.

Docker must be running locally for CDK deploy to succeed.

---

## 11. Design Decisions

### 11.1 Why Bedrock AgentCore?

AgentCore was chosen over self-managed containers (ECS/EKS) or bare Lambda for agent hosting because:

- **Managed runtime lifecycle:** AgentCore handles container provisioning, scaling, health checks, and restart.
- **Built-in A2A protocol support:** The Strands SDK provides a compliant A2A endpoint with zero boilerplate.
- **IAM-native auth:** Inter-agent calls use SigV4 automatically. No service mesh, mTLS certificates, or API keys to manage.
- **Model integration:** Bedrock models are invoked directly from within the runtime with no separate API calls or credential management.
- **STM integration:** Built-in Short-Term Memory for conversation persistence.

Trade-offs accepted:
- Container runtimes require Docker for local builds.
- Less control over container configuration (memory, CPU) compared to ECS.
- Cold start times can be significant (init includes model client setup and, for SQL Agent, Secrets Manager + Snowflake connection).

### 11.2 Why A2A Protocol?

The A2A (Agent-to-Agent) protocol was chosen over direct function calls, REST APIs, or message queues because:

- **Standardized interface:** Every agent exposes the same JSON-RPC 2.0 `message/send` method. The orchestrator uses one `invoke_specialist()` function for all four specialists.
- **Decoupled deployment:** Each agent can be deployed, updated, and scaled independently.
- **Observability:** A2A messages have standard `messageId` and `contextId` fields for tracing.
- **Future extensibility:** New specialist agents can be added by deploying a new runtime and adding a tool to the orchestrator. The protocol does not change.

### 11.3 Why Text Markers for Charts?

Several approaches were considered for chart generation:

| Approach                    | Rejected Because                                    |
|-----------------------------|-----------------------------------------------------|
| Structured output / JSON mode | Loses natural language response; requires dual calls |
| Separate "chart" artifact type in A2A | Requires protocol extension; markers get stripped at intermediaries |
| Frontend-side LLM call      | Adds latency, cost, and complexity                  |
| Server-side image rendering  | Static images; no interactivity; large payloads     |

**Text markers win** because they:
- Travel transparently through every layer (AgentCore, A2A response, Lambda).
- Allow a single LLM response to contain prose + chart data.
- Are trivially parsed by a regex on the Lambda side.
- Enable the frontend to render interactive Plotly charts (zoom, pan, hover, PNG export).

### 11.4 Why Lambda Web Adapter Over Mangum?

Mangum wraps ASGI apps for Lambda but only supports `BUFFERED` invoke mode. This means all SSE events are accumulated and sent as a single response. LWA was chosen because:

- **Real streaming:** LWA runs uvicorn inside Lambda, enabling `RESPONSE_STREAM` invoke mode on the Function URL. SSE events arrive at the client in real time.
- **Standard ASGI:** The FastAPI app runs unmodified -- no Mangum wrapper needed.
- **Tool status updates:** Real-time `[TOOL_STATUS]` markers are sent as they are detected, giving users immediate feedback on pipeline progress.

### 11.5 Why Direct Lambda Function URL (Bypassing CloudFront for API)?

The original architecture routed all traffic through CloudFront. This was changed because:

- **CloudFront has a 60-second origin response timeout** (not configurable for custom origins). Agent queries involving the full pipeline (SQL + Analysis + Writing + Validation) routinely take 90-180 seconds.
- **Lambda Function URLs have no such timeout.** The Lambda itself has a 900-second timeout, and the Function URL inherits it.
- **The frontend calls the Function URL directly** for `/api/*` routes, using the `VITE_API_URL` environment variable set to the Function URL domain.
- **CloudFront still serves static files** (JS, CSS, images) from S3, benefiting from edge caching and the SPA routing function.

### 11.6 Model Selection Rationale

All agents currently use Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) via Bedrock cross-region inference profiles. This provides a good balance of quality and speed across all agent roles.

### 11.7 Why a Thin Lambda Proxy (Not Direct AgentCore Access)?

The Lambda handler exists as a thin translation layer between the frontend and AgentCore for several reasons:

- **JWT validation:** AgentCore runtimes use IAM auth (SigV4), not Cognito JWTs. The Lambda validates the user's Cognito token and then calls AgentCore with its IAM role.
- **Artifact extraction:** The Lambda extracts `[CHART_CONFIG]` and `[SQL_QUERY]` markers from LLM text and transforms them into frontend-compatible artifact objects.
- **Tool status detection:** The Lambda detects `[TOOL_STATUS]` markers during streaming and converts them to real-time status SSE events.
- **Protocol translation:** The frontend sends a simplified JSON body; the Lambda constructs the full A2A JSON-RPC envelope and handles response parsing.
- **CORS handling:** FastAPI's CORSMiddleware manages CORS headers centrally.
- **Request cancellation:** The Lambda tracks cancelled request IDs and terminates SSE streams.

The Lambda contains zero agent logic -- all reasoning, tool calls, and data processing happen in AgentCore runtimes.
