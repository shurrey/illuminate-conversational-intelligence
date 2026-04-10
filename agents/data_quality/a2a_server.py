#!/usr/bin/env python3
"""
Data Quality Agent - Self-contained A2A server for AgentCore deployment.

Checks whether query RESULTS make sense before the analyst sees the data.
Catches impossible values, unexpected null rates, values outside business
constraints, and other data anomalies that indicate a bad query or data issue.
"""
import json
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


# --- Business Constraint Definitions ---
BUSINESS_CONSTRAINTS = {
    "GPA": {"min": 0.0, "max": 4.0, "description": "GPA on a 4.0 scale"},
    "GRADE_NUMERIC": {"min": 0.0, "max": 4.0, "description": "Numeric grade value on 4.0 scale"},
    "PERCENTAGE": {"min": 0.0, "max": 100.0, "description": "Percentage values"},
    "COMPLETION_RATE": {"min": 0.0, "max": 100.0, "description": "Course completion percentage"},
    "ENROLLMENT_COUNT": {"min": 0, "max": 500000, "description": "Enrollment count upper bound"},
    "STUDENT_COUNT": {"min": 0, "max": 500000, "description": "Student count upper bound"},
    "COURSE_COUNT": {"min": 0, "max": 100000, "description": "Course count upper bound"},
}


def _parse_markdown_table(text: str) -> list[dict]:
    """Extract rows from markdown tables found in the text."""
    rows = []
    lines = text.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect table header line (starts and ends with |)
        if line.startswith("|") and line.endswith("|"):
            headers = [h.strip() for h in line.split("|")[1:-1]]
            # Skip separator line
            if i + 1 < len(lines) and re.match(r'^\|[\s\-|]+\|$', lines[i + 1].strip()):
                i += 2
                # Read data rows
                while i < len(lines):
                    row_line = lines[i].strip()
                    if not row_line.startswith("|"):
                        break
                    values = [v.strip() for v in row_line.split("|")[1:-1]]
                    if len(values) == len(headers):
                        row_dict = {}
                        for h, v in zip(headers, values):
                            row_dict[h] = v
                        rows.append(row_dict)
                    i += 1
                continue
        i += 1
    return rows


def _run_quality_checks(question: str, data_text: str, sql_query: str) -> dict:
    """Run programmatic data quality checks. Returns structured results."""
    checks = {
        "row_count": {"passed": True, "details": ""},
        "null_rate": {"passed": True, "details": ""},
        "value_ranges": {"passed": True, "details": "", "warnings": []},
        "percentage_sums": {"passed": True, "details": ""},
        "anomalies": [],
    }

    # Parse any markdown tables in the data
    rows = _parse_markdown_table(data_text)

    if not rows:
        checks["row_count"]["passed"] = True
        checks["row_count"]["details"] = "No tabular data found to check (may be a summary response)"
        return checks

    # Row count check
    row_count = len(rows)
    checks["row_count"]["details"] = f"{row_count} rows returned"
    if row_count == 0:
        checks["row_count"]["passed"] = False
        checks["row_count"]["details"] = "Query returned 0 rows — table may be empty or filter too restrictive"
        checks["anomalies"].append({
            "type": "empty_result",
            "severity": "warning",
            "message": "Query returned no results. The table may be empty or the filter conditions too restrictive.",
        })

    # Null rate check per column
    if rows:
        headers = list(rows[0].keys())
        for col in headers:
            null_count = sum(1 for r in rows if r.get(col, "").upper() in ("NULL", "", "NONE", "N/A"))
            if row_count > 0 and null_count / row_count > 0.5:
                checks["null_rate"]["passed"] = False
                checks["null_rate"]["details"] += f"Column '{col}' has {null_count}/{row_count} null values ({null_count*100//row_count}%). "
                checks["anomalies"].append({
                    "type": "high_null_rate",
                    "severity": "warning",
                    "column": col,
                    "null_rate": f"{null_count*100//row_count}%",
                    "message": f"Column '{col}' has a high null rate — data may be incomplete.",
                })

    # Value range checks based on business constraints
    if rows:
        headers_upper = {h.upper(): h for h in rows[0].keys()}
        for constraint_key, bounds in BUSINESS_CONSTRAINTS.items():
            # Check if any column name contains the constraint key
            matching_cols = [
                orig for upper, orig in headers_upper.items()
                if constraint_key in upper
            ]
            for col in matching_cols:
                for r in rows:
                    try:
                        val = float(r.get(col, "").replace(",", "").replace("%", ""))
                        if val < bounds["min"] or val > bounds["max"]:
                            checks["value_ranges"]["passed"] = False
                            warning = (
                                f"Column '{col}' has value {val} outside expected range "
                                f"[{bounds['min']}, {bounds['max']}] ({bounds['description']})"
                            )
                            if warning not in checks["value_ranges"]["warnings"]:
                                checks["value_ranges"]["warnings"].append(warning)
                                checks["anomalies"].append({
                                    "type": "out_of_range",
                                    "severity": "error",
                                    "column": col,
                                    "value": val,
                                    "expected_range": [bounds["min"], bounds["max"]],
                                    "message": warning,
                                })
                    except (ValueError, AttributeError):
                        pass

    # Percentage sum check — if a column looks like percentages, check they sum to ~100
    if rows:
        for col in rows[0].keys():
            col_upper = col.upper()
            if any(kw in col_upper for kw in ("PERCENT", "PCT", "RATE", "SHARE", "PROPORTION")):
                try:
                    values = []
                    for r in rows:
                        val_str = r.get(col, "").replace(",", "").replace("%", "")
                        if val_str and val_str.upper() not in ("NULL", "", "NONE"):
                            values.append(float(val_str))
                    if values and len(values) > 1:
                        total = sum(values)
                        if abs(total - 100.0) > 5.0 and total > 0:
                            # Only flag if it looks like it SHOULD sum to 100
                            if 50 < total < 200:
                                checks["percentage_sums"]["passed"] = False
                                checks["percentage_sums"]["details"] = (
                                    f"Column '{col}' values sum to {total:.1f}%, "
                                    f"expected ~100%. This may indicate missing categories or double-counting."
                                )
                except (ValueError, AttributeError):
                    pass

    return checks


# --- System Prompt ---
DATA_QUALITY_SYSTEM_PROMPT = """You are the Data Quality Agent for an educational data analytics system.
Your job is to check whether query results make sense BEFORE the Analyst interprets them.

## Your Role
You receive query results + the original question. You check for data anomalies that
could lead to incorrect analysis. You are the sanity check between raw SQL results and
the Analyst.

## What You Check
1. **Row count reasonableness**: Is 0 rows suspicious? Are thousands of rows expected?
2. **Value ranges**: GPA should be 0-4.0, percentages 0-100%, counts should be positive
3. **Null rates**: If a key column has >50% nulls, the data may be unreliable
4. **Temporal consistency**: Are dates in the expected range? Any future dates that shouldn't exist?
5. **Statistical sanity**: Do percentages sum to ~100%? Are counts consistent across breakdowns?
6. **Business logic**: Do enrollment counts make sense for an institution? Are there more instructors than students?

## Educational Domain Benchmarks
- Typical institution: 1,000-50,000 students
- Course enrollment: 10-500 students per course (depends on institution size)
- GPA: 0.0-4.0 (values outside this range indicate a different grading scale)
- Course completion rate: typically 70-90%
- Grade distribution: roughly normal, centered around B (3.0)
- Instructor-to-student ratio: typically 1:15 to 1:30

## Response Format
Use the check_data_quality tool, then provide your assessment as JSON:
```json
{
  "quality_status": "good|warning|poor",
  "confidence": 0.0-1.0,
  "checks_passed": ["list of passed checks"],
  "issues": [
    {
      "severity": "error|warning|info",
      "category": "range|null|count|consistency|temporal",
      "message": "Specific description of the issue",
      "suggestion": "What to do about it"
    }
  ],
  "safe_for_analysis": true|false,
  "summary": "Brief overall assessment"
}
```

## Important
- Be pragmatic — not every anomaly is a problem
- Flag errors (must fix) vs warnings (worth noting) vs info (FYI)
- If safe_for_analysis is false, the orchestrator will re-route to SQL
- If the data looks good, say so concisely — don't over-explain"""


@tool
def check_data_quality(question: str, data: str, sql_query: str = "") -> str:
    """Receive query results for data quality validation.

    Args:
        question: The user's original question.
        data: Query results to check (typically markdown tables from the SQL agent).
        sql_query: Optional SQL query that produced these results.

    Returns:
        Data quality check results including programmatic checks and context for LLM assessment.
    """
    # Run programmatic checks
    quality_checks = _run_quality_checks(question, data, sql_query)

    parts = [
        f"## User Question\n{question}",
        f"\n## Query Results\n{data}",
    ]
    if sql_query:
        parts.append(f"\n## SQL Query\n```sql\n{sql_query}\n```")

    parts.append(f"\n## Programmatic Check Results\n```json\n{json.dumps(quality_checks, indent=2)}\n```")

    parts.append(
        "\n## Your Task\n"
        "Review the data and programmatic check results. Assess overall data quality:\n"
        "1. Are the programmatic check findings valid or false positives?\n"
        "2. Are there any issues the programmatic checks missed?\n"
        "3. Does the data make sense for the question being asked?\n"
        "4. Is this data safe to pass to the Analyst for interpretation?\n"
        "Return your assessment as structured JSON."
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
    name="Illuminate Data Quality Agent",
    description="Validates query result sanity: checks value ranges, null rates, statistical consistency, and business logic before analysis.",
    model=bedrock_model,
    tools=[check_data_quality],
    system_prompt=DATA_QUALITY_SYSTEM_PROMPT,
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
