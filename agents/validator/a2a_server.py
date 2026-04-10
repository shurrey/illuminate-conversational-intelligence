#!/usr/bin/env python3
"""
Validator Agent - Self-contained A2A server for AgentCore deployment.

Uses bedrock_agentcore.runtime.a2a.build_a2a_app() to create a Starlette app
with proper /ping and A2A routes for AgentCore.

The `app` object is exposed at module level so that AgentCore's runtime can
import it (e.g., `uvicorn a2a_server:app`).
"""
import os
import re
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

# --- FERPA PII patterns for rule-based checks ---
FERPA_PII_PATTERNS = [
    (r'\b\d{3}-\d{2}-\d{4}\b', 'SSN (xxx-xx-xxxx)'),
    (r'\b\d{9}\b', 'SSN without dashes (9 digits)'),
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'Email address'),
    (r'\b\d{10}\b', 'Phone number (10 digits)'),
    (r'\b\(\d{3}\)\s*\d{3}-\d{4}\b', 'Phone number (xxx) xxx-xxxx'),
    (r'\b\d{3}-\d{3}-\d{4}\b', 'Phone number xxx-xxx-xxxx'),
    (r'\b\d{3}\.\d{3}\.\d{4}\b', 'Phone number xxx.xxx.xxxx'),
]

# Error taxonomy categories for structured feedback
ERROR_CATEGORIES = {
    "pii_leak": "PII detected in response — individual student data exposed",
    "bad_aggregation": "Data not properly aggregated — fewer than 5 individuals per group",
    "sql_injection": "Dangerous SQL detected — potential injection or unauthorized operation",
    "impossible_data": "Data values are mathematically impossible or clearly fabricated",
    "missing_data": "Response does not address the user's question",
    "inconsistent_data": "Data is internally inconsistent (e.g., percentages don't sum to 100%)",
}

# --- System Prompt ---
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

When validating, provide your assessment as structured JSON:
```json
{
  "status": "passed|failed|warning",
  "confidence": 0.0-1.0,
  "blocked": false,
  "categories": [],
  "fix_suggestions": [],
  "summary": "brief explanation"
}
```

Error categories for structured feedback:
- pii_leak: Individual student data exposed
- bad_aggregation: Fewer than 5 individuals per group
- sql_injection: Dangerous SQL detected
- impossible_data: Mathematically impossible values
- missing_data: Response doesn't address the question
- inconsistent_data: Internally inconsistent data

When validation fails, include specific fix_suggestions that tell the orchestrator exactly what
to fix and which agent to re-route to. For example:
- "Remove FIRST_NAME column and aggregate by department instead" → re-route to SQL agent
- "Data shows 150% completion rate which is impossible — re-query with corrected logic" → re-route to SQL agent
- "Response doesn't mention enrollment trends the user asked about" → re-route to writer agent"""

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
        The formatted context for the agent to validate, including rule-based check results
        and structured error categorization.
    """
    import json as _json

    # Run rule-based PII checks with pattern descriptions
    pii_findings = []
    for pattern, description in FERPA_PII_PATTERNS:
        matches = re.findall(pattern, response_text, re.IGNORECASE)
        if matches:
            pii_findings.append({
                "type": description,
                "count": len(matches),
                "category": "pii_leak",
            })

    # Run SQL safety checks if SQL is provided
    sql_findings = []
    if sql_query:
        sql_upper = sql_query.strip().upper()
        dangerous_patterns = [
            ("DROP", "sql_injection"),
            ("DELETE", "sql_injection"),
            ("INSERT", "sql_injection"),
            ("UPDATE", "sql_injection"),
            ("ALTER", "sql_injection"),
            ("TRUNCATE", "sql_injection"),
            ("GRANT", "sql_injection"),
            ("REVOKE", "sql_injection"),
        ]
        for keyword, category in dangerous_patterns:
            if keyword in sql_upper:
                sql_findings.append({
                    "keyword": keyword,
                    "category": category,
                    "fix_suggestion": f"Remove {keyword} operation — only SELECT/WITH queries are allowed.",
                })

    # Build structured validation context
    rule_check_results = {
        "pii_check": {
            "passed": len(pii_findings) == 0,
            "findings": pii_findings,
        },
        "sql_safety_check": {
            "passed": len(sql_findings) == 0,
            "findings": sql_findings,
        },
        "error_categories": ERROR_CATEGORIES,
    }

    parts = [
        f"User Question: {user_query}",
        f"\nResponse to Validate:\n{response_text}",
        f"\n## Rule-Based Check Results\n```json\n{_json.dumps(rule_check_results, indent=2)}\n```",
    ]
    if sql_query:
        parts.append(f"\nSQL Query:\n{sql_query}")
    if data_summary:
        parts.append(f"\nData Summary:\n{data_summary}")

    parts.append(
        "\n## Your Validation Task\n"
        "Evaluate the response and return your assessment as structured JSON with these fields:\n"
        "- status: 'passed' | 'failed' | 'warning'\n"
        "- confidence: 0.0-1.0\n"
        "- blocked: true/false (only true for serious violations)\n"
        "- categories: list of error category keys from the taxonomy above (if any)\n"
        "- fix_suggestions: list of specific, actionable fixes for each issue\n"
        "- summary: brief explanation of the validation result"
    )

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
        "inferenceConfig": {"temperature": 0.0},
        **({"amazon-bedrock-guardrailConfig": guardrail_config} if guardrail_config else {}),
    },
)
log(f"  Model: {model_id} (temperature=0.0)")

strands_agent = Agent(
    name="Illuminate Validator Agent",
    description="Validates responses for FERPA compliance, PII safety, data accuracy, and response quality.",
    model=bedrock_model,
    tools=[validate_response],
    system_prompt=VALIDATOR_SYSTEM_PROMPT,
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
