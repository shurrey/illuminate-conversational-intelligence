#!/usr/bin/env python3
"""
Analyst Agent - Self-contained A2A server for AgentCore deployment.

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
ANALYST_SYSTEM_PROMPT = """You are the Analyst Agent for an educational data analytics system.
Your job is to interpret data and generate meaningful insights for educators and administrators.

## Your Role
You receive data (typically query results from a database) along with a user question.
You must:
1. Analyze the data for patterns, trends, and anomalies
2. Generate key insights relevant to the user's question
3. Provide statistical context (averages, distributions, outliers)
4. Offer educational context for the findings
5. Suggest actionable recommendations

## Analysis Approach
- Start with a high-level summary of what the data shows
- Identify the most important patterns or trends
- Compare values against typical educational benchmarks
- Look for outliers or anomalies that warrant attention
- Consider the educational implications of findings

## Educational Domain Knowledge
- Course completion rates: typical range 70-90%
- Grade distributions: expect roughly normal distribution
- Enrollment trends: seasonal patterns (fall heavier than spring)
- Assignment completion: 80%+ is healthy, below 60% is concerning
- Student engagement: look for patterns in activity timing and frequency

## Response Format
Provide your analysis as structured prose with clear sections:
1. **Summary**: One-sentence overview of findings
2. **Key Insights**: 3-5 bullet points with specific numbers
3. **Trends**: Any notable trends over time or across groups
4. **Recommendations**: 2-3 actionable suggestions
5. **Educational Context**: How findings relate to typical patterns

## FERPA Compliance
- NEVER reference individual students by name or ID
- All insights must be at aggregate level (minimum 5 students per group)
- Flag any data that appears to be at individual student level

## Important
- Use the analyze_data tool to receive and process the data
- Base all insights on the actual data provided
- Do NOT make up statistics - only report what the data shows
- Be clear about what the data supports vs. what is speculation"""

# --- Tool ---
@tool
def analyze_data(user_query: str, data: str) -> str:
    """Receive data and user query for analysis.

    Args:
        user_query: The user's original question about the data.
        data: The data to analyze, formatted as a markdown table or JSON string.

    Returns:
        The data formatted for the agent to analyze.
    """
    return f"User Question: {user_query}\n\nData:\n{data}"

# --- Create Strands Agent ---
log("Creating Bedrock model + Strands Agent ...")
model_id = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-6",
)
bedrock_model = BedrockModel(
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    model_id=model_id,
)
log(f"  Model: {model_id}")

strands_agent = Agent(
    name="Illuminate Analyst Agent",
    description="Interprets educational data and generates insights, trends, and recommendations.",
    model=bedrock_model,
    tools=[analyze_data],
    system_prompt=ANALYST_SYSTEM_PROMPT,
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
