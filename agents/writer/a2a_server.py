#!/usr/bin/env python3
"""
Writer Agent - Self-contained A2A server for AgentCore deployment.

Uses bedrock_agentcore.runtime.a2a.build_a2a_app() to create a Starlette app
with proper /ping and A2A routes for AgentCore.

The `app` object is exposed at module level so that AgentCore's runtime can
import it (e.g., `uvicorn a2a_server:app`).
"""
import os
import sys
from pathlib import Path


def log(msg):
    print(msg, file=sys.stderr, flush=True)


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
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from bedrock_agentcore.runtime.a2a import build_a2a_app

# --- System Prompt ---
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
    "us.anthropic.claude-sonnet-4-6",
)

# Bedrock Guardrails — FERPA compliance filter runs before/after LLM inference
guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
guardrail_version = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "")
guardrail_config = None
if guardrail_id and guardrail_version:
    guardrail_config = {
        "guardrailIdentifier": guardrail_id,
        "guardrailVersion": guardrail_version,
        "trace": "enabled",
    }
    log(f"  Guardrail: {guardrail_id} v{guardrail_version}")

bedrock_model = BedrockModel(
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    model_id=model_id,
    additional_model_request_fields={
        "inferenceConfig": {"temperature": 0.3},
        **({"amazon-bedrock-guardrailConfig": guardrail_config} if guardrail_config else {}),
    },
)
log(f"  Model: {model_id} (temperature=0.3)")

strands_agent = Agent(
    name="Illuminate Writer Agent",
    description="Crafts clear, natural language responses from data and analysis for educational users.",
    model=bedrock_model,
    tools=[write_response],
    system_prompt=WRITER_SYSTEM_PROMPT,
    callback_handler=None,
)

executor = StrandsA2AExecutor(strands_agent)
log("DONE: Agent initialized")

# Build the Starlette app with /ping and A2A routes — exposed at module level
# so AgentCore runtime can import it as `a2a_server:app` or `a2a_server.app`
app = build_a2a_app(executor)
log("App built (Starlette with /ping + A2A routes)")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9000"))
    log(f"Starting uvicorn on 0.0.0.0:{port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port)
