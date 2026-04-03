#!/usr/bin/env python3
"""
Orchestrator Agent - Self-contained A2A server for AgentCore deployment.

Uses bedrock_agentcore.runtime.a2a.build_a2a_app() to create a Starlette app
with proper /ping and A2A routes for AgentCore.

Coordinates specialist agents (SQL, Analyst, Writer, Validator) via
boto3 invoke_agent_runtime (SigV4 auth).

The `app` object is exposed at module level so that AgentCore's runtime can
import it (e.g., `uvicorn a2a_server:app`).
"""
import json
import os
import sys
import uuid
from pathlib import Path


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def invoke_specialist(client, runtime_arn: str, message: str) -> str:
    """Invoke a specialist agent via boto3 and return text response."""
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

    body = json.loads(response["response"].read().decode())

    # Extract text from A2A response
    if "result" in body:
        result = body["result"]
        if isinstance(result, dict):
            # Try artifacts first
            for artifact in result.get("artifacts", []):
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text" and part.get("text"):
                        return part["text"]

            # Try direct message parts
            for part in result.get("parts", []):
                if part.get("kind") == "text" and part.get("text"):
                    return part["text"]

            # Try history (last agent message)
            for msg in reversed(result.get("history", [])):
                if msg.get("role") == "agent":
                    for part in msg.get("parts", []):
                        if part.get("kind") == "text" and part.get("text"):
                            return part["text"]

            return json.dumps(result, indent=2)
        return str(result)
    elif "error" in body:
        return f"Error from agent: {json.dumps(body['error'])}"
    return json.dumps(body, indent=2)


# Load .env.agentcore
env_file = Path(__file__).parent / ".env.agentcore"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value and key not in os.environ:
            os.environ[key] = value
    log(f"Loaded {env_file}")

log("Importing dependencies ...")
import boto3
from botocore.config import Config
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from bedrock_agentcore.runtime.a2a import build_a2a_app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Create boto3 client for AgentCore (SigV4 auth via IAM role)
# Use extended timeout since specialist agents involve LLM calls
region = os.environ.get("AWS_REGION", "us-east-1")
_agentcore_client = boto3.client(
    "bedrock-agentcore",
    region_name=region,
    config=Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 1}),
)
log("  Created bedrock-agentcore boto3 client (300s timeout)")

# Runtime ARNs from environment
SQL_AGENT_ARN = os.environ.get("SQL_AGENT_ARN", "")
ANALYST_AGENT_ARN = os.environ.get("ANALYST_AGENT_ARN", "")
WRITER_AGENT_ARN = os.environ.get("WRITER_AGENT_ARN", "")
VALIDATOR_AGENT_ARN = os.environ.get("VALIDATOR_AGENT_ARN", "")

log(f"  SQL: {SQL_AGENT_ARN}")
log(f"  Analyst: {ANALYST_AGENT_ARN}")
log(f"  Writer: {WRITER_AGENT_ARN}")
log(f"  Validator: {VALIDATOR_AGENT_ARN}")

# --- Specialist Agent Tools ---
@tool
def query_database(message: str) -> str:
    """Send a query to the SQL Agent which generates and executes SQL against Snowflake.

    Args:
        message: Natural language description of what data to retrieve.

    Returns:
        Query results formatted as markdown tables.
    """
    log(f"  -> SQL Agent: {message[:100]}...")
    return invoke_specialist(_agentcore_client, SQL_AGENT_ARN, message)


@tool
def analyze_data(message: str) -> str:
    """Send data to the Analyst Agent for trend analysis and statistical insights.

    Args:
        message: Query results and context to analyze.

    Returns:
        Analysis with trends, patterns, and recommendations.
    """
    log(f"  -> Analyst Agent: {message[:100]}...")
    return invoke_specialist(_agentcore_client, ANALYST_AGENT_ARN, message)


@tool
def write_response(message: str) -> str:
    """Send data and analysis to the Writer Agent to craft a polished response.

    Args:
        message: Data, analysis, and original query for response writing.

    Returns:
        Clear natural language response for educational administrators.
    """
    log(f"  -> Writer Agent: {message[:100]}...")
    return invoke_specialist(_agentcore_client, WRITER_AGENT_ARN, message)


@tool
def validate_response(message: str) -> str:
    """Send the response to the Validator Agent for FERPA compliance and accuracy checks.

    Args:
        message: The complete response to validate with original query and data.

    Returns:
        Validation result indicating pass/fail and any issues found.
    """
    log(f"  -> Validator Agent: {message[:100]}...")
    return invoke_specialist(_agentcore_client, VALIDATOR_AGENT_ARN, message)


# --- System Prompt ---
SYSTEM_PROMPT = """You are the Illuminate Orchestrator, the central coordinator for an educational data analytics system.

## Your Role
You coordinate specialist agents to answer questions about educational data stored in a Snowflake data warehouse.

## Available Tools

1. **query_database**: Send natural language queries to the SQL Agent. It generates and executes
   SQL queries against the Snowflake data warehouse and returns results as markdown tables.

2. **analyze_data**: Send query results to the Analyst Agent for interpretation. It identifies
   trends, patterns, statistical insights, and provides recommendations.

3. **write_response**: Send data and analysis to the Writer Agent. It crafts clear, polished
   natural language responses suitable for educational administrators.

4. **validate_response**: Send the final response to the Validator Agent. It checks for FERPA
   compliance, data accuracy, and PII leakage before the response is delivered.

## Workflow
For data-related questions, follow this pipeline:
1. Use `query_database` to get the data from Snowflake
2. Use `analyze_data` with the query results to get insights
3. Use `write_response` with data + analysis to craft the final response
4. Use `validate_response` to verify FERPA compliance and accuracy
5. Return the validated response to the user

For simple informational questions, you may answer directly without invoking all agents.

## Creating Visualizations (Charts)

When the user asks for a chart, graph, plot, or visualization, you MUST include the chart data
in your response using the special markers below. The system will automatically render an
interactive chart in the user's browser.

**Format:** Include exactly this structure in your response text:

[CHART_CONFIG]
{
  "chart_type": "bar",
  "title": "Chart Title Here",
  "x_axis": "key_name_for_x",
  "y_axis": "key_name_for_y",
  "data": [
    {"key_name_for_x": "Label1", "key_name_for_y": 100},
    {"key_name_for_x": "Label2", "key_name_for_y": 200}
  ]
}
[/CHART_CONFIG]

- Supported chart_type values: "bar", "line", "pie", "scatter", "histogram"
- The "data" array MUST contain actual data from the query results — never placeholder or example data
- x_axis and y_axis must match the key names in the data objects
- If you need data, use `query_database` first, then include the chart config with real data
- You can include multiple [CHART_CONFIG] blocks for multiple charts
- Always include a brief text description along with the chart

## Real-Time Status Updates

Before calling ANY tool, you MUST output a status marker on its own line so the frontend
can show the user what is happening. The format is: [TOOL_STATUS:tool_name]

For example, your output should look like:

[TOOL_STATUS:query_database]
(then call query_database)

[TOOL_STATUS:analyze_data]
(then call analyze_data)

This is critical for user experience — always emit the marker IMMEDIATELY before each tool call.
Do NOT include these markers in your final written response to the user.

## Important Rules
- Always start with `query_database` when the user asks about data
- When the user asks for a chart/graph/visualization, you MUST include a [CHART_CONFIG] block with actual data
- Do NOT just describe what a chart would look like — include the [CHART_CONFIG] block so it renders
- Pass the FULL results between agents — do not summarize prematurely
- If validation fails, revise the response and re-validate
- Never expose individual student data or PII
- Keep your final response focused and actionable for educational administrators"""

# --- Create Strands Agent with STM Memory ---
log("Creating Bedrock model + Strands Agent ...")
model_id = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-6",
)
bedrock_model = BedrockModel(
    region_name=region,
    model_id=model_id,
)
log(f"  Model: {model_id}")

# Configure AgentCore STM for persistent conversation history
session_manager = None
memory_id = os.environ.get("BEDROCK_AGENTCORE_MEMORY_ID", "")
if memory_id:
    try:
        from bedrock_agentcore.memory.integrations.strands import (
            AgentCoreMemorySessionManager,
            AgentCoreMemoryConfig,
        )
        stm_config = AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id="default",  # overridden per-request via middleware
            actor_id="orchestrator",
        )
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=stm_config,
            region_name=region,
        )
        log(f"  STM memory configured: {memory_id}")
    except Exception as e:
        log(f"  STM memory setup failed (will use in-memory fallback): {e}")

strands_agent = Agent(
    name="Illuminate Orchestrator",
    description="Central coordinator for educational data queries. Routes requests to SQL, Analyst, Writer, and Validator agents.",
    model=bedrock_model,
    system_prompt=SYSTEM_PROMPT,
    tools=[query_database, analyze_data, write_response, validate_response],
    callback_handler=None,
    session_manager=session_manager,
)

executor = StrandsA2AExecutor(strands_agent)
log("DONE: Agent initialized")


# --- Session Routing Middleware ---
class SessionRoutingMiddleware(BaseHTTPMiddleware):
    """Set the STM session_id from the A2A contextId before each request.

    This ensures that when the strands Agent processes a message, its
    AgentCoreMemorySessionManager loads/saves conversation history for
    the correct conversation (identified by contextId).
    """

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)

        body_bytes = await request.body()
        try:
            body_json = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return await call_next(request)

        # Route STM for both message/send and message/stream
        if body_json.get("method") in ("message/send", "message/stream"):
            params = body_json.get("params", {})
            message = params.get("message", {})
            context_id = message.get("contextId")
            if context_id and session_manager is not None:
                try:
                    session_manager.config.session_id = context_id
                    log(f"  STM session routed to: {context_id}")
                except Exception as e:
                    log(f"  STM session routing failed: {e}")

        # For message/stream, return early — BaseHTTPMiddleware's _receive
        # override breaks SSE streaming. Starlette caches request.body()
        # so the downstream handler can still read it.
        if body_json.get("method") != "message/send":
            return await call_next(request)

        # For message/send, re-inject the body for the downstream handler
        async def receive():
            return {"type": "http.request", "body": body_bytes}
        request._receive = receive

        return await call_next(request)


# Build the Starlette app with /ping and A2A routes — exposed at module level
# so AgentCore runtime can import it as `a2a_server:app` or `a2a_server.app`
app = build_a2a_app(executor)

# Add session routing middleware so STM uses the right contextId per request
app.add_middleware(SessionRoutingMiddleware)
log("App built (Starlette with /ping + A2A routes + STM session routing)")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9000"))
    log(f"Starting uvicorn on 0.0.0.0:{port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port)
