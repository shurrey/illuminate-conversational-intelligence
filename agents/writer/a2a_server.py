"""
Writer Agent - Self-contained A2A server for AgentCore deployment.

Crafts clear, natural language responses from data and analysis.
Zero `from agents.*` imports.
"""
import os
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

    # --- System Prompt (inlined from agents/writer/agent.py) ---
    WRITER_SYSTEM_PROMPT = """You are the Writer Agent for an educational data analytics system.
Your job is to craft clear, helpful responses for users.

## Your Role
You receive:
1. The user's original question
2. Raw data from the database
3. Analysis and insights from the Analyst (when available)

You must:
1. Write a clear, conversational response
2. Answer the user's specific question directly
3. Include key insights naturally
4. Format data appropriately
5. Suggest helpful follow-up questions

## Response Guidelines
- Start with a direct answer to the question
- Use natural language, not technical jargon
- Reference specific numbers from the data
- Keep it concise but complete
- End with 2-3 suggested follow-up questions

## Data Formatting
- For small datasets (< 10 rows): Include as markdown table in response
- For larger datasets: Summarize key points, mention full data is available
- Always mention the row count

## Tone
- Professional but friendly
- Confident but not arrogant
- Helpful and proactive

## Example Structure
```
[Direct answer to the question]

[Key findings with specific numbers]

[Brief interpretation/context]

**You might also want to know:**
- [Follow-up question 1]
- [Follow-up question 2]
```

## Important
- Use the write_response tool to receive the data and context
- Do NOT return JSON - write natural prose
- Base your response on the actual data provided
- If analysis is provided, weave those insights into your response naturally"""

    # --- Tool ---
    @tool
    def write_response(user_query: str, data: str, analysis: str = "") -> str:
        """Receive data and context for crafting a response.

        Args:
            user_query: The user's original question.
            data: The data to present, formatted as a markdown table or JSON string.
            analysis: Optional analysis/insights from the Analyst agent.

        Returns:
            The formatted context for the agent to craft a response.
        """
        parts = [f"User Question: {user_query}", f"\nData:\n{data}"]
        if analysis:
            parts.append(f"\nAnalysis:\n{analysis}")
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
        name="Illuminate Writer Agent",
        description="Crafts clear, natural language responses from data and analysis for educational users.",
        model=bedrock_model,
        tools=[write_response],
        system_prompt=WRITER_SYSTEM_PROMPT,
        callback_handler=None,
    )

    # --- Wrap in A2AServer ---
    log("Creating A2AServer ...")
    runtime_url = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9003/")
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
                "result": {"text": f"Writer Agent init failed: {startup_error}"},
                "id": "error",
            },
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
