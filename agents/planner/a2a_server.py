#!/usr/bin/env python3
"""
Planner Agent - Self-contained A2A server for AgentCore deployment.

Receives user questions + conversation context, classifies difficulty, and
produces a structured execution plan for the orchestrator. For simple queries
it passes through directly; for complex queries it decomposes into ordered
sub-tasks with dependencies.

Uses extended thinking (budgetTokens) so the model reasons deeply about HOW
to answer before producing the plan.
"""
import json
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
PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for an educational data analytics system.
Your job is to analyze user questions and produce structured execution plans.

## Your Role
You receive the user's raw question (and optionally conversation context).
You must:
1. Classify the question's difficulty
2. Identify what data/schemas are likely needed
3. For simple questions, produce a pass-through plan
4. For complex questions, decompose into ordered sub-tasks with dependencies
5. Flag any ambiguity that needs clarification before proceeding

## Difficulty Classification
- **simple**: Single-table lookup, direct count/aggregate, schema discovery
  Examples: "How many students?", "List all schemas", "What tables are in CDM_LMS?"
- **medium**: Multi-table join, comparison across dimensions, basic trend analysis
  Examples: "Enrollment by term", "GPA comparison across departments", "Top 10 courses by enrollment"
- **complex**: Multi-step analysis, cross-domain correlation, time-series with derived metrics
  Examples: "How does enrollment correlate with GPA trends over the last 5 terms?",
  "Which departments have declining completion rates and what factors might explain it?"

## Plan Structure
Return your plan as a JSON object using the `create_plan` tool:
```json
{
  "difficulty": "simple|medium|complex",
  "needs_clarification": false,
  "clarification_question": null,
  "steps": [
    {
      "step_id": 1,
      "agent": "schema_expert|sql|analyst|writer|validator",
      "action": "Brief description of what this step does",
      "input_description": "What data/context this step needs",
      "depends_on": [],
      "notes": "Optional guidance for the agent"
    }
  ],
  "schemas_needed": ["CDM_LMS"],
  "tables_likely_needed": ["PERSON", "PERSON_COURSE", "TERM"],
  "reasoning": "Brief explanation of why this plan was chosen"
}
```

## Planning Rules
- For **simple** queries: 2-3 steps (SQL → Writer → Validator), skip Analyst if no analysis needed
- For **medium** queries: Full pipeline (Schema Expert → SQL → Analyst → Writer → Validator)
- For **complex** queries: Multiple SQL steps, potentially with analyst feedback loops
- Always include Validator as the final step
- If the question is ambiguous (e.g., "show me the data"), flag needs_clarification=true
- Consider whether the Schema Expert should run first to narrow table/column selection
- Think about which tables and joins are likely needed BEFORE the SQL agent runs
- If the question references previous conversation, note that context should be passed through

## Educational Domain Knowledge
- CDM_LMS schema contains: PERSON, COURSE, PERSON_COURSE (enrollment), GRADE, TERM, etc.
- PERSON has INSTITUTION_ROLE: 'S' (student), 'I' (instructor)
- PERSON_COURSE links students to courses (enrollment records)
- GRADE stores grade records linked to PERSON and COURSE
- TERM defines academic terms/semesters
- Common analyses: enrollment trends, GPA distributions, completion rates, grade distributions

## Important
- Use the create_plan tool to structure your plan
- Think deeply about the decomposition before responding
- Be specific about what each step needs as input
- Consider FERPA implications in your plan (flag if individual data might be needed)"""


@tool
def create_plan(
    question: str,
    difficulty: str,
    needs_clarification: bool,
    steps: str,
    schemas_needed: str,
    tables_likely_needed: str,
    reasoning: str,
    clarification_question: str = "",
    conversation_context: str = "",
) -> str:
    """Create a structured execution plan for the orchestrator.

    Args:
        question: The user's original question.
        difficulty: Question difficulty classification - 'simple', 'medium', or 'complex'.
        needs_clarification: Whether the question is ambiguous and needs user clarification.
        steps: JSON array string of plan steps, each with step_id, agent, action, input_description, depends_on, notes.
        schemas_needed: JSON array string of schema names likely needed (e.g., '["CDM_LMS"]').
        tables_likely_needed: JSON array string of table names likely needed (e.g., '["PERSON", "COURSE"]').
        reasoning: Brief explanation of why this plan was chosen.
        clarification_question: If needs_clarification is true, the question to ask the user.
        conversation_context: Summary of relevant conversation history, if any.

    Returns:
        The structured plan as formatted JSON for the orchestrator.
    """
    try:
        steps_parsed = json.loads(steps) if isinstance(steps, str) else steps
        schemas_parsed = json.loads(schemas_needed) if isinstance(schemas_needed, str) else schemas_needed
        tables_parsed = json.loads(tables_likely_needed) if isinstance(tables_likely_needed, str) else tables_likely_needed
    except json.JSONDecodeError as e:
        return f"ERROR: Failed to parse plan JSON: {e}"

    plan = {
        "question": question,
        "difficulty": difficulty,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question or None,
        "conversation_context": conversation_context or None,
        "steps": steps_parsed,
        "schemas_needed": schemas_parsed,
        "tables_likely_needed": tables_parsed,
        "reasoning": reasoning,
    }

    return json.dumps(plan, indent=2)


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

# Extended thinking for deeper reasoning on complex decomposition
bedrock_model = BedrockModel(
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    model_id=model_id,
    additional_model_request_fields={
        "inferenceConfig": {"temperature": 0.0},
        **({"amazon-bedrock-guardrailConfig": guardrail_config} if guardrail_config else {}),
    },
)
log(f"  Model: {model_id} (temperature=0.0)")

strands_agent = Agent(
    name="Illuminate Planner Agent",
    description="Analyzes user questions, classifies difficulty, and produces structured execution plans for the orchestrator.",
    model=bedrock_model,
    tools=[create_plan],
    system_prompt=PLANNER_SYSTEM_PROMPT,
    callback_handler=None,
)

executor = StrandsA2AExecutor(strands_agent)
log("DONE: Agent initialized")

# Build the Starlette app with /ping and A2A routes
app = build_a2a_app(executor)
log("App built (Starlette with /ping + A2A routes)")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9000"))
    log(f"Starting uvicorn on 0.0.0.0:{port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port)
