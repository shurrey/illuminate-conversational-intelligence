"""
Validator Agent - Self-contained A2A server for AgentCore deployment.

Validates responses for FERPA compliance, accuracy, and safety.
Uses both rule-based checks and LLM-as-a-Judge. Zero `from agents.*` imports.
"""
import os
import re
import sys
import traceback
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

startup_log = []
startup_error = None


def log(msg):
    startup_log.append(msg)
    print(msg, file=sys.stderr, flush=True)


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
    from strands import Agent, tool
    from strands.models import BedrockModel
    from strands.multiagent.a2a import A2AServer

    # --- FERPA PII patterns for rule-based checks ---
    FERPA_PII_PATTERNS = [
        r'\b\d{3}-\d{2}-\d{4}\b',                                    # SSN
        r'\b\d{9}\b',                                                  # SSN without dashes
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',     # Email
        r'\b\d{10}\b',                                                 # Phone numbers
        r'\b\(\d{3}\)\s*\d{3}-\d{4}\b',                              # Phone with parens
    ]

    # --- System Prompt (inlined from agents/validator/agent.py) ---
    VALIDATOR_SYSTEM_PROMPT = """You are a Validation Agent for an educational data analytics system.
Your role is to validate responses before they are shown to users.

IMPORTANT CONTEXT: The specialist agents execute SQL queries via MCP tools internally.
You may not always see the SQL queries, but if the response contains specific statistics,
percentages, counts, or structured data tables, ASSUME the data came from real database queries.
Do NOT block responses just because you cannot see the underlying SQL.

You must check for:

1. **SQL Safety** (only if SQL is provided): Ensure no dangerous SQL operations
2. **Data Plausibility**: Check that numeric results are internally consistent
   - Percentages should sum to ~100%
   - Counts should be reasonable for educational data
   - Statistics should be mathematically consistent
3. **FERPA Compliance** (CRITICAL): Ensure no personally identifiable information (PII) is exposed
   - No individual student names in grade contexts
   - No SSNs, phone numbers, or personal emails
   - Aggregations must have at least 5 individuals
4. **Response Quality**: Ensure the response addresses the user's question

DO NOT block responses for:
- Containing specific statistics without visible SQL (the agent queried the database internally)
- Presenting data in table format (this is expected behavior)
- Follow-up questions that reference previous data
- Visualization/formatting requests for previously queried data

ONLY block responses for:
- Clear PII violations (individual student names, SSNs, emails)
- Data that is mathematically impossible or clearly fabricated
- Dangerous SQL if provided

## Important
- Use the validate_response tool to receive the response for validation
- Return your assessment as a clear validation result
- Be strict about FERPA/PII compliance
- Be lenient about data source verification since agents query internally

When validating, provide your assessment including:
- Overall status: passed, failed, warning, or needs_review
- Confidence score (0.0-1.0)
- Specific checks performed and their results
- Whether the response should be blocked (only for serious violations)
- Any recommendations for improvement"""

    # --- Tool ---
    @tool
    def validate_response(user_query: str, response_text: str, sql_query: str = "", data_summary: str = "") -> str:
        """Receive a response for FERPA/PII/accuracy validation.

        Args:
            user_query: The user's original question.
            response_text: The response text to validate.
            sql_query: Optional SQL query that produced the data.
            data_summary: Optional summary of query result data.

        Returns:
            The formatted context for the agent to validate, including rule-based check results.
        """
        # Run quick rule-based PII checks
        pii_findings = []
        for pattern in FERPA_PII_PATTERNS:
            if re.search(pattern, response_text, re.IGNORECASE):
                pii_findings.append(f"PII pattern matched: {pattern}")

        rule_results = "Rule-based PII check: "
        if pii_findings:
            rule_results += "FAILED - " + "; ".join(pii_findings)
        else:
            rule_results += "PASSED - No obvious PII patterns detected"

        parts = [
            f"User Question: {user_query}",
            f"\nResponse to Validate:\n{response_text}",
            f"\n{rule_results}",
        ]
        if sql_query:
            parts.append(f"\nSQL Query:\n{sql_query}")
        if data_summary:
            parts.append(f"\nData Summary:\n{data_summary}")

        return "\n".join(parts)

    # --- Create Strands Agent ---
    log("Creating Bedrock model + Strands Agent ...")
    model_id = os.environ.get(
        "BEDROCK_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )
    bedrock_model = BedrockModel(
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        model_id=model_id,
    )
    log(f"  Model: {model_id}")

    strands_agent = Agent(
        name="Illuminate Validator Agent",
        description="Validates responses for FERPA compliance, PII safety, data accuracy, and response quality.",
        model=bedrock_model,
        tools=[validate_response],
        system_prompt=VALIDATOR_SYSTEM_PROMPT,
        callback_handler=None,
    )

    # --- Wrap in A2AServer ---
    log("Creating A2AServer ...")
    runtime_url = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9004/")
    a2a_server = A2AServer(
        agent=strands_agent,
        http_url=runtime_url,
        serve_at_root=True,
    )

    log("Building FastAPI app ...")
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"status": "healthy"}

    @app.get("/_startup_log")
    def get_startup_log():
        return {"log": startup_log, "error": startup_error}

    app.mount("/", a2a_server.to_fastapi_app())
    log("DONE: App fully initialized")

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
                "result": {"text": f"Validator Agent init failed: {startup_error}"},
                "id": "error",
            },
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
