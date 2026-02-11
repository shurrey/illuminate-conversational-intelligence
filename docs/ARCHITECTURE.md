# Illuminate Conversational Intelligence -- Architecture

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Agent Architecture](#2-agent-architecture)
3. [Request Flow](#3-request-flow)
4. [Authentication and Security](#4-authentication-and-security)
5. [Data Flow for Chart and Visualization Generation](#5-data-flow-for-chart-and-visualization-generation)
6. [Conversation Context Management](#6-conversation-context-management)
7. [Infrastructure](#7-infrastructure)
8. [Design Decisions](#8-design-decisions)

---

## 1. System Overview

Illuminate Conversational Intelligence (ICI) is a multi-agent system that enables educational administrators to query, analyze, and visualize institutional data through natural language. Users ask questions in plain English; the system translates those into SQL queries against a Snowflake data warehouse, analyzes the results, writes a polished response, validates it for FERPA compliance, and returns the answer -- optionally with interactive charts.

All agent logic runs on **AWS Bedrock AgentCore** as self-contained A2A (Agent-to-Agent) protocol runtimes. A thin Lambda proxy sits between the frontend and the orchestrator. The frontend is a React SPA served from S3 via CloudFront.

### High-Level Architecture

```
                           +---------------------------+
                           |     React SPA (Vite)      |
                           |  Cognito Auth, Plotly.js  |
                           +-------------|-------------+
                                         |
                    Static assets        | API calls
                    via CloudFront       | (HTTPS, JWT)
                         |               |
            +------------|---------------|------------------+
            |            v               v                  |
            |   +----------------+   +------------------+  |
            |   |  S3 Bucket     |   | Lambda Fn URL    |  |
            |   |  (OAC, priv.)  |   | (FastAPI+Mangum) |  |
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
                    |                                                  |
                    |   +------------------------------------------+  |
                    |   |         Orchestrator Agent                |  |
                    |   |  (Sonnet 4, Strands SDK, A2A Server)     |  |
                    |   |  Context middleware, specialist routing   |  |
                    |   +-----|---------|---------|-----------|-----+  |
                    |         |         |         |           |        |
                    |   invoke_agent_runtime (SigV4, A2A JSON-RPC)    |
                    |         |         |         |           |        |
                    |         v         v         v           v        |
                    |   +-------+ +---------+ +--------+ +---------+  |
                    |   |  SQL  | | Analyst | | Writer | |Validator|  |
                    |   |Opus 4 | | Opus 4  | |Sonnet 4| |Sonnet 4 |  |
                    |   +---|---+ +---------+ +--------+ +---------+  |
                    |       |                                          |
                    +-------|------------------------------------------+
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
| Frontend       | React 18, TypeScript, Vite, TailwindCSS, Plotly  |
| Auth           | Amazon Cognito (User Pool + SRP auth)             |
| API Proxy      | AWS Lambda (Python 3.11, FastAPI, Mangum)         |
| Agent Runtime  | AWS Bedrock AgentCore, Strands Agents SDK         |
| Agent Protocol | A2A (Agent-to-Agent) over JSON-RPC 2.0            |
| Models         | Claude Sonnet 4, Claude Opus 4 (via Bedrock)      |
| Data Store     | Snowflake (snowflake-connector-python)            |
| Secrets        | AWS Secrets Manager                                |
| CDN / WAF      | CloudFront, WAFv2 (CLOUDFRONT scope)              |
| IaC            | CloudFormation (4 stacks)                         |

---

## 2. Agent Architecture

The system comprises five agents, each deployed as an independent Bedrock AgentCore runtime. Every agent is a self-contained `a2a_server.py` file with zero cross-module imports (`from agents.*`), which is a hard requirement imposed by how AgentCore flattens source archives to the zip root at deploy time.

Each agent follows the same structural pattern:

1. Load `.env.agentcore` for runtime configuration.
2. Import the Strands SDK (`Agent`, `tool`, `BedrockModel`, `A2AServer`).
3. Define domain-specific `@tool` functions.
4. Create a `strands.Agent` with a system prompt and tools.
5. Wrap it in an `A2AServer` and mount onto a FastAPI application.
6. Expose `/ping` for health checks and `/_startup_log` for diagnostics.

### 2.1 Orchestrator Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/orchestrator/a2a_server.py`           |
| Model       | Claude Sonnet 4 (`claude-sonnet-4-20250514`)  |
| Role        | Central coordinator; routes to specialists     |
| Tools       | `query_database`, `analyze_data`, `write_response`, `validate_response` |

The orchestrator is the only agent the Lambda proxy communicates with. It receives a user's natural language question and determines which specialist agents to invoke and in what order. Its four tools are thin wrappers that call `invoke_specialist()`, which sends an A2A JSON-RPC `message/send` request to the target agent's runtime via `boto3.client('bedrock-agentcore').invoke_agent_runtime()`.

The orchestrator also hosts a FastAPI **context enrichment middleware** that intercepts incoming A2A `message/send` requests, prepends conversation history from an in-memory store, and passes the enriched message to the Strands agent. See Section 6 for details.

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
| Model       | Claude Opus 4 (`claude-opus-4-20250514`)      |
| Role        | Generate and execute SQL against Snowflake     |
| Tools       | `list_objects`, `describe_object`, `run_snowflake_query` |

The SQL agent connects directly to Snowflake via `snowflake-connector-python`. Credentials are loaded from AWS Secrets Manager (`illuminate/dev/snowflake`) at startup. The connection is lazily initialized and reused across requests.

Key safeguards:
- Only `SELECT`, `WITH`, and `SHOW` statements are allowed; the `run_snowflake_query` tool rejects anything else.
- Fully qualified table names are required (`DATABASE.CDM_LMS.TABLE_NAME`).
- The system prompt enforces FERPA rules: aggregate data only, minimum 5 individuals per group, `PERSON_ID` used only for JOINs.
- Default `LIMIT 100` to prevent unbounded result sets.

Opus 4 was chosen for SQL generation because it produces more accurate and complex queries than Sonnet 4, particularly for multi-table JOINs and window functions.

### 2.3 Analyst Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/analyst/a2a_server.py`                |
| Model       | Claude Opus 4 (`claude-opus-4-20250514`)      |
| Role        | Interpret data; identify trends and patterns   |
| Tools       | `analyze_data`                                |

The analyst receives query results (typically markdown tables) and the original user question. It produces structured analysis with:
- A one-sentence summary
- 3-5 key insights with specific numbers
- Trend identification
- 2-3 actionable recommendations
- Educational context (e.g., course completion benchmarks)

Opus 4 was chosen for its superior analytical reasoning on numeric data.

### 2.4 Writer Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/writer/a2a_server.py`                 |
| Model       | Claude Sonnet 4 (`claude-sonnet-4-20250514`)  |
| Role        | Craft clear, user-facing natural language      |
| Tools       | `write_response`                              |

The writer transforms raw data and analysis into conversational prose for educational administrators. It formats data as markdown tables for small datasets and summaries for larger ones, and ends each response with 2-3 suggested follow-up questions.

### 2.5 Validator Agent

| Property    | Value                                         |
|-------------|-----------------------------------------------|
| File        | `agents/validator/a2a_server.py`              |
| Model       | Claude Sonnet 4 (`claude-sonnet-4-20250514`)  |
| Role        | FERPA compliance, PII detection, accuracy      |
| Tools       | `validate_response`                           |

The validator implements a two-tier compliance check:

**Tier 1 -- Rule-based PII detection (regex):**
Runs before the LLM sees the response. Patterns checked:
- SSNs (`\b\d{3}-\d{2}-\d{4}\b` and `\b\d{9}\b`)
- Email addresses
- Phone numbers (10-digit and parenthesized formats)

**Tier 2 -- LLM-as-a-Judge:**
The Sonnet 4 model evaluates the response for:
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
  |    {message, contextId} |                         |                       |
  |    Authorization: Bearer <JWT>                    |                       |
  |------------------------>|                         |                       |
  |                         |                         |                       |
  |  2. Validate JWT        |                         |                       |
  |    (Cognito JWKS)       |                         |                       |
  |                         |                         |                       |
  |  3. Build A2A JSON-RPC  |                         |                       |
  |    message/send payload |                         |                       |
  |                         |                         |                       |
  |                         | 4. invoke_agent_runtime |                       |
  |                         |    (boto3, SigV4)       |                       |
  |                         |------------------------>|                       |
  |                         |                         |                       |
  |                         |                         | 5. Context middleware  |
  |                         |                         |    prepends history    |
  |                         |                         |                       |
  |                         |                         | 6. Strands Agent       |
  |                         |                         |    reasons, selects    |
  |                         |                         |    tools               |
  |                         |                         |                       |
  |                         |                         | 7. query_database ---->| SQL Agent
  |                         |                         |    (invoke_agent_      | Snowflake query
  |                         |                         |     runtime, SigV4)   | returns markdown
  |                         |                         |<------- results ------|
  |                         |                         |                       |
  |                         |                         | 8. analyze_data ------>| Analyst Agent
  |                         |                         |<------- insights -----|
  |                         |                         |                       |
  |                         |                         | 9. write_response ---->| Writer Agent
  |                         |                         |<------- prose --------|
  |                         |                         |                       |
  |                         |                         | 10. validate_response >| Validator Agent
  |                         |                         |<------- pass/fail ----|
  |                         |                         |                       |
  |                         | 11. A2A response        |                       |
  |                         |    (text w/ optional     |                       |
  |                         |     [CHART_CONFIG])      |                       |
  |                         |<------------------------|                       |
  |                         |                         |                       |
  |  12. Extract chart      |                         |                       |
  |    configs from text    |                         |                       |
  |    markers, build       |                         |                       |
  |    artifact objects     |                         |                       |
  |                         |                         |                       |
  |  13. SSE: data: {type:  |                         |                       |
  |    "complete", data:    |                         |                       |
  |    {text, artifacts,    |                         |                       |
  |     contextId}}         |                         |                       |
  |<------------------------|                         |                       |
  |                         |                         |                       |
  | 14. Render text +       |                         |                       |
  |     Plotly chart        |                         |                       |
```

### Detailed Steps

1. **Browser sends request.** The frontend's `AgentClient.sendMessageStreaming()` POSTs to `/api/chat/stream` with a JSON-RPC-style body containing the message text, a `contextId` (for conversation continuity), and a `messageId`. The `Authorization: Bearer <id_token>` header carries the Cognito JWT.

2. **Lambda validates JWT.** The Lambda handler (`lambda_handler.py`) fetches the Cognito JWKS (cached for 1 hour), locates the signing key by `kid`, and verifies the RS256 signature, audience, and issuer claims. Invalid tokens receive HTTP 401.

3. **Lambda builds A2A payload.** The message is wrapped in a JSON-RPC 2.0 `message/send` request with a `messageId`, `contextId`, and a `parts` array containing a single text part.

4. **Lambda invokes the orchestrator.** The `AgentCoreA2AClient` calls `boto3.client('bedrock-agentcore').invoke_agent_runtime()` with the orchestrator's runtime ARN. Authentication is SigV4, handled automatically by boto3 using the Lambda's execution role. Timeouts: 300s read, 10s connect.

5. **Orchestrator middleware enriches context.** The FastAPI `context_enrichment_middleware` intercepts the request, looks up the `contextId` in its in-memory conversation store, and prepends previous Q&A pairs to the current message text (see Section 6).

6. **Orchestrator agent reasons.** The Strands Agent (Sonnet 4) processes the enriched message, reads the system prompt, and decides which tools to invoke.

7. **SQL Agent queries Snowflake.** The orchestrator calls `query_database()`, which invokes the SQL Agent via `invoke_agent_runtime()`. The SQL Agent (Opus 4) generates a SQL query, executes it via `snowflake-connector-python`, and returns results as a markdown table.

8. **Analyst Agent interprets results.** The orchestrator calls `analyze_data()`, forwarding query results and the original question. The Analyst Agent (Opus 4) returns structured insights.

9. **Writer Agent crafts the response.** The orchestrator calls `write_response()`, forwarding data, analysis, and the original question. The Writer Agent (Sonnet 4) returns polished prose.

10. **Validator Agent checks compliance.** The orchestrator calls `validate_response()`, forwarding the full response. The Validator Agent runs regex PII checks, then uses Sonnet 4 as an LLM judge. If validation fails, the orchestrator can revise and re-validate.

11. **Orchestrator returns the response.** The A2A response flows back through the AgentCore runtime to the Lambda proxy. The response text may contain `[CHART_CONFIG]...[/CHART_CONFIG]` markers.

12. **Lambda extracts chart configs.** A regex (`_CHART_PATTERN`) finds all `[CHART_CONFIG]` blocks, parses the JSON inside each, creates frontend-compatible chart artifact objects (with `id`, `type`, `title`, `data` fields), strips the markers from the text, and cleans up whitespace.

13. **Lambda streams SSE response.** The response is sent as a Server-Sent Events stream. The final event has `type: "complete"` with `data.text` (cleaned markdown), `data.artifacts` (chart objects), and `data.contextId`.

14. **Frontend renders the response.** `MessageBubble` displays the markdown text. If artifacts are present, `ChartRenderer` lazy-loads Plotly.js and renders interactive charts using the configuration from the artifact's data.

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

- **User Pool:** `illuminate-users-{env}` with email-based sign-in.
- **Password Policy:** Minimum 12 characters, requires upper + lower + number + symbol.
- **Auth Flows:** SRP, User Password, and Refresh Token.
- **Frontend Library:** `amazon-cognito-identity-js` handles SRP authentication directly against Cognito (no hosted UI).
- **Token Storage:** The frontend stores the auth state (user, token) in `localStorage` under the key `illuminate_auth`.
- **JWT Validation:** The Lambda validates the Cognito ID token on every request. JWKS is fetched from `https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json` and cached for 1 hour.

### 4.2 Service-to-Service Authentication (SigV4)

All inter-service communication uses AWS IAM SigV4 authentication:

- **Lambda to Orchestrator:** The Lambda's execution role (`illuminate-lambda-{env}`) has `bedrock-agentcore:InvokeAgentRuntime` permission scoped to `illuminate_orchestrator_*` runtimes.
- **Orchestrator to Specialists:** The AgentCore runtime role (`illuminate-agent-runtime-{env}`) has `bedrock-agentcore:InvokeAgentRuntime` permission scoped to `illuminate_*` runtimes.
- **Orchestrator to Bedrock Models:** The runtime role has `bedrock:InvokeModel` and `bedrock:ConverseStream` permissions for Claude models.
- **SQL Agent to Secrets Manager:** The runtime role has `secretsmanager:GetSecretValue` for the Snowflake secret.

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
3. **Validator Agent LLM-as-a-Judge:** Sonnet 4 evaluates the full response for individual student name exposure, data plausibility, and aggregation compliance.
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

## 6. Conversation Context Management

Multi-turn conversations are managed by the orchestrator's **context enrichment middleware**, not by AgentCore's built-in memory system. This was a deliberate choice for simplicity and control.

### How It Works

The orchestrator's FastAPI `context_enrichment_middleware` intercepts every incoming POST (A2A `message/send`) request:

1. **Extract contextId** from the A2A message params.
2. **Look up history** in an in-memory dictionary: `_conversations: dict[str, list[dict]]`.
3. **If history exists**, prepend it to the current message text:

```
## Previous Conversation:
User: What is the enrollment for Fall 2024?
Assistant: Total enrollment for Fall 2024 was 12,345 students across...

## Current Question:
How does that compare to Spring 2024?

Answer the current question using conversation context if relevant.
```

4. **Override the request body** so the Strands agent sees the enriched message.
5. **Store the user message** in the conversation history.
6. **Trim to MAX_HISTORY** (10 exchanges) to prevent unbounded context growth.
7. **Truncate** individual messages to 500 characters in the history to manage token budget.

### Limitations

- History is stored **in-memory on the orchestrator container**. If the AgentCore runtime restarts or scales, history is lost.
- The `contextId` must be consistent across requests for a conversation. The frontend generates a UUID per conversation and includes it in every request.
- Assistant responses are stored when the next user message arrives (the middleware records the user text, and the assistant text slot is updated externally).

### Why Not AgentCore Memory?

AgentCore provides a built-in Memory resource (`AWS::BedrockAgentCore::Memory`) that is provisioned in the CloudFormation stack. However, the in-memory middleware approach was adopted because:

- It provides full control over what context is prepended to each message.
- It avoids the complexity of integrating with AgentCore's STM (Short-Term Memory) API.
- Truncation and history-window management are trivial to implement.
- For the current scale (single orchestrator instance), in-memory storage is sufficient.

---

## 7. Infrastructure

The system is deployed via four CloudFormation stacks, each building on the outputs of previous stacks.

### Stack Dependency Chain

```
+-------------------------------+
| 1-base-infrastructure.yaml    |
| VPC, Cognito, S3, Secrets,    |
| REGIONAL WAF                  |
+---------------|---------------+
                |
        Exports: VpcId, Subnets, SG,
        UserPoolId, ArtifactsBucket,
        SnowflakeSecret, WebACLArn
                |
     +----------|----------+
     |                     |
     v                     v
+----------------------+  +---------------------+
| 2-agentcore.yaml     |  | 3-api-gateway.yaml  |
| AgentCore Gateway,   |  | Lambda function,    |
| Memory, 5 Runtimes,  |  | Function URL,       |
| IAM Role             |  | IAM Role            |
+----------------------+  +---------|-----------+
                                    |
                            Exports: FunctionUrlDomain,
                            ApiUrl
                                    |
                                    v
                          +---------------------+
                          | 4-frontend.yaml     |
                          | S3 bucket (OAC),    |
                          | CloudFront dist.,   |
                          | CLOUDFRONT WAF,     |
                          | SPA routing fn      |
                          +---------------------+
```

### Stack 1: Base Infrastructure (`1-base-infrastructure.yaml`)

| Resource            | Type                          | Details                                    |
|---------------------|-------------------------------|--------------------------------------------|
| VPC                 | `AWS::EC2::VPC`               | `10.0.0.0/16`, DNS enabled                 |
| Public Subnets (2)  | `AWS::EC2::Subnet`            | `10.0.1.0/24`, `10.0.2.0/24` (2 AZs)     |
| Private Subnets (2) | `AWS::EC2::Subnet`            | `10.0.11.0/24`, `10.0.12.0/24` (2 AZs)   |
| Internet Gateway    | `AWS::EC2::InternetGateway`   | For public subnets                         |
| NAT Gateway         | `AWS::EC2::NatGateway`        | In public subnet 1, for private egress     |
| Security Group      | `AWS::EC2::SecurityGroup`     | HTTPS (443) intra-SG only                  |
| Cognito User Pool   | `AWS::Cognito::UserPool`      | Email sign-in, strong password policy       |
| Cognito Client      | `AWS::Cognito::UserPoolClient`| SRP + password + refresh auth flows        |
| S3 Artifacts Bucket | `AWS::S3::Bucket`             | Lambda code, agent ZIPs; fully private     |
| Snowflake Secret    | `AWS::SecretsManager::Secret` | account, user, password, database, etc.    |
| WAF WebACL          | `AWS::WAFv2::WebACL`          | REGIONAL scope; rate limit + managed rules |

### Stack 2: AgentCore (`2-agentcore.yaml`)

| Resource             | Type                                  | Details                                 |
|----------------------|---------------------------------------|-----------------------------------------|
| Agent Runtime Role   | `AWS::IAM::Role`                      | bedrock:InvokeModel, agentcore:Invoke, secretsmanager, s3, logs |
| Gateway              | `AWS::BedrockAgentCore::Gateway`      | IAM authorizer for A2A                  |
| Memory               | `AWS::BedrockAgentCore::Memory`       | 24h event expiry                        |
| Orchestrator Runtime | `AWS::BedrockAgentCore::Runtime`      | Source: `agents/orchestrator.zip`       |
| Orchestrator Endpt.  | `AWS::BedrockAgentCore::RuntimeEndpoint` | Sonnet 4                             |
| SQL Runtime          | `AWS::BedrockAgentCore::Runtime`      | Source: `agents/sql.zip`                |
| SQL Endpoint         | `AWS::BedrockAgentCore::RuntimeEndpoint` | Opus 4                               |
| Analyst Runtime      | `AWS::BedrockAgentCore::Runtime`      | Source: `agents/analyst.zip`            |
| Analyst Endpoint     | `AWS::BedrockAgentCore::RuntimeEndpoint` | Opus 4                               |
| Writer Runtime       | `AWS::BedrockAgentCore::Runtime`      | Source: `agents/writer.zip`             |
| Writer Endpoint      | `AWS::BedrockAgentCore::RuntimeEndpoint` | Sonnet 4                             |
| Validator Runtime    | `AWS::BedrockAgentCore::Runtime`      | Source: `agents/validator.zip`          |
| Validator Endpoint   | `AWS::BedrockAgentCore::RuntimeEndpoint` | Sonnet 4                             |

### Stack 3: API (`3-api-gateway.yaml`)

| Resource             | Type                          | Details                                     |
|----------------------|-------------------------------|---------------------------------------------|
| Lambda Exec. Role    | `AWS::IAM::Role`              | agentcore:Invoke, secretsmanager, s3, cognito |
| Lambda Function      | `AWS::Lambda::Function`       | Python 3.11, 1024 MB, 900s timeout, VPC    |
| Lambda Function URL  | `AWS::Lambda::Url`            | AuthType: NONE, BUFFERED invoke mode        |
| URL Permission (1)   | `AWS::Lambda::Permission`     | `lambda:InvokeFunctionUrl`, Principal: `*`  |
| URL Permission (2)   | `AWS::Lambda::Permission`     | `lambda:InvokeFunction`, `InvokedViaFunctionUrl: true` |
| Log Group            | `AWS::Logs::LogGroup`         | 7 days (dev), 30 days (prod)                |

Note: The Lambda Function URL requires **two** permissions -- `InvokeFunctionUrl` and `InvokeFunction` with the `InvokedViaFunctionUrl` condition. Missing either one causes 403 errors.

### Stack 4: Frontend (`4-frontend.yaml`)

| Resource             | Type                              | Details                                   |
|----------------------|-----------------------------------|-------------------------------------------|
| S3 Bucket            | `AWS::S3::Bucket`                 | Fully private (all public access blocked) |
| Bucket Policy        | `AWS::S3::BucketPolicy`          | Allow only CloudFront OAC                  |
| Origin Access Control| `AWS::CloudFront::OriginAccessControl` | SigV4 signing for S3 origin          |
| SPA Routing Function | `AWS::CloudFront::Function`       | Rewrites non-file paths to `/index.html`  |
| CLOUDFRONT WAF       | `AWS::WAFv2::WebACL`             | Same rules as base, CLOUDFRONT scope       |
| CloudFront Dist.     | `AWS::CloudFront::Distribution`  | Two origins: S3 (default) + API (Function URL) |

CloudFront behaviors:
- `/*` (default) -- S3 origin with SPA routing function.
- `/api/*` -- Lambda Function URL origin, caching disabled, forwards Authorization header.
- `/health` -- Lambda Function URL origin.

---

## 8. Design Decisions

### 8.1 Why Bedrock AgentCore?

AgentCore was chosen over self-managed containers (ECS/EKS) or bare Lambda for agent hosting because:

- **Managed runtime lifecycle:** AgentCore handles container provisioning, scaling, health checks, and restart. No Dockerfiles, ECS task definitions, or Kubernetes manifests to maintain.
- **Built-in A2A protocol support:** The Strands SDK `A2AServer` provides a compliant A2A endpoint with zero boilerplate.
- **IAM-native auth:** Inter-agent calls use SigV4 automatically. No service mesh, mTLS certificates, or API keys to manage.
- **Model integration:** Bedrock models are invoked directly from within the runtime with no separate API calls or credential management.

Trade-offs accepted:
- AgentCore's `agentcore deploy` flattens ZIP files, requiring self-contained `a2a_server.py` files with no relative imports.
- Less control over container configuration (memory, CPU, environment) compared to ECS.
- Cold start times can be significant (init includes model client setup and, for SQL Agent, Secrets Manager + Snowflake connection).

### 8.2 Why A2A Protocol?

The A2A (Agent-to-Agent) protocol was chosen over direct function calls, REST APIs, or message queues because:

- **Standardized interface:** Every agent exposes the same JSON-RPC 2.0 `message/send` method. The orchestrator uses one `invoke_specialist()` function for all four specialists.
- **Decoupled deployment:** Each agent can be deployed, updated, and scaled independently. Changing the SQL Agent's model from Opus 4 to a future model requires updating only the SQL agent's endpoint -- the orchestrator's code is unchanged.
- **Observability:** A2A messages have standard `messageId` and `contextId` fields for tracing.
- **Future extensibility:** New specialist agents can be added by deploying a new runtime and adding a tool to the orchestrator. The protocol does not change.

### 8.3 Why Text Markers for Charts?

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

### 8.4 Why Direct Lambda Function URL (Bypassing CloudFront for API)?

The original architecture routed all traffic through CloudFront. This was changed because:

- **CloudFront has a 60-second origin response timeout** (not configurable for custom origins). Agent queries involving the full pipeline (SQL + Analysis + Writing + Validation) routinely take 90-180 seconds.
- **Lambda Function URLs have no such timeout.** The Lambda itself has a 900-second timeout, and the Function URL inherits it.
- **The frontend calls the Function URL directly** for `/api/*` routes, using the `VITE_API_URL` environment variable set to the Function URL domain.
- **CloudFront still serves static files** (JS, CSS, images) from S3, benefiting from edge caching and the SPA routing function.
- **CloudFront still has the API as an origin** in the template for `/api/*` paths, which provides the WAF protection for any requests that do go through CloudFront (e.g., health checks, short queries).

### 8.5 Model Selection Rationale

| Agent        | Model     | Rationale                                                    |
|--------------|-----------|--------------------------------------------------------------|
| Orchestrator | Sonnet 4  | Good at routing and tool selection; fast enough for coordination overhead |
| SQL          | Opus 4    | Superior SQL generation accuracy, especially for complex JOINs and window functions |
| Analyst      | Opus 4    | Stronger analytical reasoning on numeric data and pattern identification |
| Writer       | Sonnet 4  | Excellent prose quality at lower latency; writing does not need Opus-level reasoning |
| Validator    | Sonnet 4  | Compliance checks are well-scoped; Sonnet handles rule application well |

Opus 4 is reserved for the two agents where reasoning quality most directly impacts correctness (SQL generation and data analysis). Sonnet 4 is used where speed matters more than depth (orchestration, writing, validation).

### 8.6 Why a Thin Lambda Proxy (Not Direct AgentCore Access)?

The Lambda handler exists as a thin translation layer between the frontend and AgentCore for several reasons:

- **JWT validation:** AgentCore runtimes use IAM auth (SigV4), not Cognito JWTs. The Lambda validates the user's Cognito token and then calls AgentCore with its IAM role.
- **Chart extraction:** The Lambda extracts `[CHART_CONFIG]` markers from LLM text and transforms them into frontend-compatible artifact objects. This logic does not belong in the agent or the frontend.
- **Protocol translation:** The frontend sends a simplified JSON body; the Lambda constructs the full A2A JSON-RPC envelope and handles response parsing.
- **CORS handling:** FastAPI's CORSMiddleware manages CORS headers centrally.
- **Request cancellation:** The Lambda tracks cancelled request IDs and terminates SSE streams.

The Lambda contains zero agent logic -- all reasoning, tool calls, and data processing happen in AgentCore runtimes.
