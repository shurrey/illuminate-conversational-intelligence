"""
Orchestrator Agent - Self-contained A2A server for AgentCore deployment.

Coordinates specialist agents (SQL, Analyst, Writer, Validator) via
boto3 invoke_agent_runtime (SigV4 auth). Zero `from agents.*` imports.
"""
import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

startup_log = []
startup_error = None


def log(msg):
    startup_log.append(msg)
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


try:
    log("Loading .env.agentcore ...")
    env_file = Path(__file__).parent / ".env.agentcore"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key and value and key not in os.environ:
                os.environ[key] = value
        log(f"  Loaded {env_file}")

    log("Importing dependencies ...")
    import boto3
    from botocore.config import Config
    from strands import Agent, tool
    from strands.models import BedrockModel
    from strands.multiagent.a2a import A2AServer
    # starlette Response no longer needed — middleware doesn't buffer response

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

## Important Rules
- Always start with `query_database` when the user asks about data
- When the user asks for a chart/graph/visualization, you MUST include a [CHART_CONFIG] block with actual data
- Do NOT just describe what a chart would look like — include the [CHART_CONFIG] block so it renders
- Pass the FULL results between agents — do not summarize prematurely
- If validation fails, revise the response and re-validate
- Never expose individual student data or PII
- Keep your final response focused and actionable for educational administrators"""

    # --- Create Strands Agent ---
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

    strands_agent = Agent(
        name="Illuminate Orchestrator",
        description="Central coordinator for educational data queries. Routes requests to SQL, Analyst, Writer, and Validator agents.",
        model=bedrock_model,
        system_prompt=SYSTEM_PROMPT,
        tools=[query_database, analyze_data, write_response, validate_response],
        callback_handler=None,
    )

    # --- Wrap in A2AServer ---
    log("Creating A2AServer ...")
    runtime_url = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")
    a2a_server = A2AServer(
        agent=strands_agent,
        http_url=runtime_url,
        serve_at_root=True,
    )

    # --- Conversation History Store ---
    _conversations: dict[str, list[dict]] = {}
    MAX_HISTORY = 10  # max Q&A exchanges to keep per context

    def build_context_prompt(context_id: str, current_text: str) -> str:
        """Prepend conversation history to the current message."""
        history = _conversations.get(context_id, [])
        if not history:
            return current_text

        history_lines = []
        for entry in history:
            user_text = entry.get("user", "")
            assistant_text = entry.get("assistant", "")
            if len(user_text) > 500:
                user_text = user_text[:500] + "..."
            if assistant_text:
                if len(assistant_text) > 500:
                    assistant_text = assistant_text[:500] + "..."
                history_lines.append(f"User: {user_text}")
                history_lines.append(f"Assistant: {assistant_text}")
            else:
                history_lines.append(f"User: {user_text}")

        return (
            "## Previous Conversation:\n"
            + "\n".join(history_lines)
            + "\n\n## Current Question:\n"
            + current_text
            + "\n\nAnswer the current question using conversation context if relevant."
        )

    log("Building FastAPI app ...")
    app = FastAPI()

    @app.middleware("http")
    async def context_enrichment_middleware(request: Request, call_next):
        """Intercept A2A message/send requests: enrich context + inject chart artifacts."""
        # Only act on POST requests — GET is ping, agent card, etc.
        if request.method != "POST":
            return await call_next(request)

        # Read request body
        body_bytes = await request.body()
        try:
            body_json = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return await call_next(request)

        # Only act on message/send
        if body_json.get("method") != "message/send":
            return await call_next(request)

        # Extract contextId and message text
        params = body_json.get("params", {})
        message = params.get("message", {})
        context_id = message.get("contextId")
        parts = message.get("parts", [])

        original_text = ""
        for part in parts:
            if part.get("kind") == "text" and part.get("text"):
                original_text = part["text"]
                break

        if not original_text:
            return await call_next(request)

        # Enrich with history if contextId exists and has history
        if context_id and context_id in _conversations and _conversations[context_id]:
            enriched_text = build_context_prompt(context_id, original_text)
            for part in parts:
                if part.get("kind") == "text":
                    part["text"] = enriched_text
                    break
            modified_body = json.dumps(body_json).encode()
            log(f"  Context enrichment: {context_id} ({len(_conversations[context_id])} exchanges)")
        else:
            modified_body = body_bytes

        # Override request._receive so downstream sees modified body
        async def receive():
            return {"type": "http.request", "body": modified_body}
        request._receive = receive

        # Store user text for conversation history
        # Assistant text is stored via /store_history callback from Lambda
        if context_id:
            if context_id not in _conversations:
                _conversations[context_id] = []
            _conversations[context_id].append({
                "user": original_text,
                "assistant": "",
            })
            if len(_conversations[context_id]) > MAX_HISTORY:
                _conversations[context_id] = _conversations[context_id][-MAX_HISTORY:]

        # Pass response through WITHOUT buffering — streaming goes directly to client
        # Chart extraction is handled by the Lambda handler (not here)
        response = await call_next(request)
        return response

    @app.get("/ping")
    def ping():
        return {"status": "healthy"}

    @app.get("/_startup_log")
    def get_startup_log():
        return {"log": startup_log, "error": startup_error}

    app.mount("/", a2a_server.to_fastapi_app())
    log("DONE: App fully initialized (with context enrichment middleware)")

except Exception as e:
    startup_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    log(f"FAILED: {startup_error}")

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"status": "error", "failed_at": startup_log[-1] if startup_log else "unknown"}

    @app.get("/_startup_log")
    def get_startup_log():
        return {"log": startup_log, "error": startup_error}

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def error_handler(request: Request, path: str):
        return JSONResponse(
            status_code=200,
            content={
                "jsonrpc": "2.0",
                "result": {"text": f"Orchestrator init failed: {startup_error}"},
                "id": "error",
            },
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
