"""
chat_engine.py — Core Bedrock Converse engine for Illuminate.

Fetches the Blackboard Data Dictionary at import time, compiles it into a
schema reference, builds a system prompt, and provides sync and async
interfaces to Claude via the Bedrock Converse API with tool_use.
"""

import asyncio
import json
import logging
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import boto3

import snowflake_client

logger = logging.getLogger("API-PROXY")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

_DICT_BASE_URL = os.environ.get(
    "DATA_DICTIONARY_URL",
    "https://us.data.api.blackboard.com/api/v1/data/dictionary",
)
_DICT_TIMEOUT = int(os.environ.get("DATA_DICTIONARY_TIMEOUT", "15"))
_PRIORITY_SCHEMAS = {"CDM_LMS", "CDM_SIS", "CDM_ALY"}

_bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# Data Dictionary fetch (runs at module import time)
# ---------------------------------------------------------------------------


def _fetch_json(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_DICT_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _fetch_data_dictionary():
    urls = {
        "submodels": f"{_DICT_BASE_URL}/submodels",
        "definitions": f"{_DICT_BASE_URL}/definitions",
        "erd": f"{_DICT_BASE_URL}/erd",
    }
    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(_fetch_json, url) for name, url in urls.items()}
        for name, future in futures.items():
            results[name] = future.result()
    return results["submodels"], results["definitions"], results["erd"]


def _compile_schema_reference(submodels, definitions, erd):
    def_index = {}
    for d in definitions:
        fqn = d.get("name", "")
        if fqn:
            def_index[fqn.upper()] = d

    schema_names = {}
    for s in submodels:
        schema_names[s.get("schemaId", "").upper()] = s.get(
            "displayName", s.get("name", "")
        )

    lines = []
    for schema_block in erd.get("schemas", []):
        tables = schema_block.get("tables", [])
        if not tables:
            continue
        first_fqn = tables[0].get("FQN", "")
        schema_id = (
            first_fqn.split(".")[0].upper() if "." in first_fqn else "UNKNOWN"
        )
        display_name = schema_names.get(schema_id, schema_id)
        is_priority = schema_id in _PRIORITY_SCHEMAS

        lines.append(f"\n## {schema_id} ({display_name})")
        if not is_priority:
            table_names = [t.get("FQN", "").split(".")[-1] for t in tables]
            lines.append(f"Tables: {', '.join(table_names)}")
            lines.append(
                "Use execute_sql with DESCRIBE TABLE for column details if needed."
            )
            continue

        for table in tables:
            table_fqn = table.get("FQN", "")
            table_name = (
                table_fqn.split(".")[-1] if "." in table_fqn else table_fqn
            )
            table_def = def_index.get(table_fqn.upper(), {})
            table_desc = table_def.get("text", "")
            lines.append(f"\n### {table_name}")
            if table_desc:
                lines.append(table_desc[:120])
            for col in table.get("columns", []):
                col_name = col.get("name", "")
                data_type = col.get("dataType", "")
                flags = []
                if col.get("isPrimaryKey"):
                    flags.append("PK")
                if col.get("isForeignKey"):
                    target = col.get("primaryKeyTableFQN", "").split(".")[-1]
                    flags.append(f"FK→{target}")
                col_fqn = f"{table_fqn}.{col_name}".upper()
                col_def = def_index.get(col_fqn, {})
                specs = col_def.get("technicalSpecifications", [])
                if any(s.get("isPii") for s in specs):
                    flags.append("PII")
                desc = col_def.get("text", "")
                desc_short = f" -- {desc[:80]}" if desc else ""
                flag_str = f" [{','.join(flags)}]" if flags else ""
                lines.append(
                    f"  {col_name} {data_type}{flag_str}{desc_short}"
                )

        fks = schema_block.get("foreignKeys", [])
        if fks:
            lines.append(f"\nRelationships in {schema_id}:")
            for fk in fks:
                fk_info = fk.get("foreignKey", {})
                uk_info = fk.get("uniqueKey", {})
                fk_cols = ".".join(
                    c["name"] for c in fk_info.get("columns", [])
                )
                uk_table = uk_info.get("tableFQN", "")
                uk_cols = ".".join(
                    c["name"] for c in uk_info.get("columns", [])
                )
                lines.append(
                    f"  {fk_info.get('tableFQN','')}.{fk_cols} → {uk_table}.{uk_cols}"
                )

    return "\n".join(lines)


# Resolve database name — env var preferred, fall back to Secrets Manager
def _resolve_database() -> str:
    db = os.environ.get("SNOWFLAKE_DATABASE", "")
    if db:
        return db
    try:
        secret_name = os.environ.get(
            "SNOWFLAKE_SECRET_NAME", "illuminate/dev/snowflake"
        )
        region = os.environ.get("AWS_REGION", "us-east-1")
        sm = boto3.client("secretsmanager", region_name=region)
        resp = sm.get_secret_value(SecretId=secret_name)
        creds = json.loads(resp["SecretString"])
        return creds.get("database", "ILLUMINATE")
    except Exception as exc:
        logger.warning("Could not resolve database name from Secrets Manager: %s", exc)
        return "ILLUMINATE"


# Run at import time
try:
    logger.info("Fetching Blackboard Data Dictionary…")
    _submodels, _definitions, _erd = _fetch_data_dictionary()
    _compiled_schema = _compile_schema_reference(_submodels, _definitions, _erd)
    logger.info(
        "Data Dictionary compiled (%d chars)", len(_compiled_schema)
    )
except Exception as _dict_exc:
    logger.error("Failed to fetch Data Dictionary: %s", _dict_exc)
    _compiled_schema = "(Data Dictionary unavailable — use DESCRIBE TABLE to inspect schemas.)"

_database = _resolve_database()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are Illuminate, an AI assistant for educational data analytics. You help educators, administrators, and analysts understand student outcomes, course performance, and institutional trends by querying a Snowflake data warehouse and presenting insights clearly.

## Database Configuration
- Snowflake database: `{_database}`
- All table references must use fully-qualified names: `{_database}.<SCHEMA>.<TABLE>`
- Available schemas and tables are documented in the Schema Reference below.

## Schema Reference
{_compiled_schema}

## SQL Query Guidelines
- Always use fully-qualified table names: `{_database}.CDM_LMS.COURSE_MAIN`
- Only reference columns that appear in the Schema Reference above; use `DESCRIBE TABLE` if uncertain.
- Join tables using documented foreign keys; prefer primary key (ID column) joins.
- Default result limit is 100 rows unless the user requests more. Never exceed 1000.
- For student filters: use `COURSE_ROLE = 'S'`; for instructors: `COURSE_ROLE = 'I'`.
- When filtering by course or user, prefer parameterized queries using `:param_name` syntax.
- Write efficient queries — avoid full-table scans when filters are available.
- Prefer CTEs (WITH clauses) for readability when multiple steps are needed.

## FERPA Compliance Rules
- Never include PII columns (first name, last name, email, SSN, phone, address, date of birth, password) in a SELECT result without aggregation.
- When reporting on individual students, aggregate data and suppress groups smaller than 5.
- If a user requests raw PII, explain the FERPA restriction and offer an aggregated alternative.

## Parameterized Queries
When a query includes user-supplied values (course ID, term, student count threshold, etc.), use Snowflake bind variable syntax `:param_name` and declare the parameters in a `[QUERY_PARAMS]` block at the end of your response:

```
[QUERY_PARAMS]
{{"param_name": "value", "other_param": 42}}
```

## Chart Visualization
When your results are well-suited to a chart, include a `[CHART_CONFIG]` block after your main response. Use this JSON structure:

```
[CHART_CONFIG]
{{"type": "bar"|"line"|"pie"|"scatter", "title": "...", "x_key": "column_name", "y_key": "column_name", "color_key": "optional_column"}}
```

Only include `[CHART_CONFIG]` when a chart genuinely adds value (trends, distributions, comparisons). Do not include it for single-value or text-only results.

## SQL Transparency
Always show the SQL you executed in a `[SQL_QUERY]` block:

```
[SQL_QUERY]
SELECT ...
FROM ...
```

Place this block before your analysis so users can review and trust the query.

## Response Style
- Be concise and actionable. Lead with the key finding, then provide supporting detail.
- Use markdown tables for multi-row results.
- Round percentages to one decimal place.
- When results are empty, suggest why and offer an alternative query.
- End each response with 1–2 suggested follow-up questions relevant to the data shown.
- Do not speculate beyond what the data shows. If uncertain, say so and suggest a clarifying query.
"""

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "execute_sql",
        "description": (
            "Execute a read-only SQL query against the Snowflake data warehouse. "
            "Only SELECT, WITH, SHOW, and DESCRIBE statements are allowed. "
            "The query is validated for safety before execution. "
            "Returns columns and rows as JSON, or an error message."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to execute.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Optional bind variable values.",
                        "additionalProperties": True,
                    },
                },
                "required": ["sql"],
            }
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return the result as a JSON string."""
    if tool_name == "execute_sql":
        sql = tool_input.get("sql", "")
        params = tool_input.get("params") or None
        logger.info(f"execute_sql: {sql[:300]}")
        result = snowflake_client.validate_and_execute(sql, params)
        if "error" in result:
            logger.warning(f"SQL error: {result['error']}")
        else:
            logger.info(f"SQL success: {len(result.get('rows', []))} rows")
        return json.dumps(result, default=str)
    return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ---------------------------------------------------------------------------
# Sync interface
# ---------------------------------------------------------------------------

_MAX_ROUNDS = 5
_INFERENCE_CONFIG = {"temperature": 0.0, "maxTokens": 4096}


def send_message(user_message: str, history: list) -> tuple[str, list]:
    """Send a user message and return (response_text, updated_messages_list).

    Args:
        user_message: The user's text input.
        history: Existing conversation as a list of Bedrock Converse messages.

    Returns:
        Tuple of (response_text, updated_messages_list).
    """
    messages = list(history)
    messages.append({"role": "user", "content": [{"text": user_message}]})

    for _round in range(_MAX_ROUNDS):
        response = _bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": [{"toolSpec": t} for t in TOOLS]},
            inferenceConfig=_INFERENCE_CONFIG,
        )

        output_message = response["output"]["message"]
        messages.append(output_message)

        stop_reason = response.get("stopReason", "")

        # Check for tool use
        tool_uses = [
            block
            for block in output_message.get("content", [])
            if "toolUse" in block
        ]

        if not tool_uses or stop_reason == "end_turn":
            # Extract text response
            text_parts = [
                block["text"]
                for block in output_message.get("content", [])
                if "text" in block
            ]
            return "\n".join(text_parts), messages

        # Dispatch all tool calls and collect results
        tool_results = []
        for block in tool_uses:
            tool_use = block["toolUse"]
            result_content = _dispatch_tool(
                tool_use["name"], tool_use.get("input", {})
            )
            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result_content}],
                    }
                }
            )

        messages.append({"role": "user", "content": tool_results})

    # Exceeded max rounds — return whatever text we have
    last = messages[-1] if messages else {}
    text_parts = [
        block["text"]
        for block in last.get("content", [])
        if isinstance(block, dict) and "text" in block
    ]
    return "\n".join(text_parts) or "I was unable to complete the request.", messages


# ---------------------------------------------------------------------------
# Async streaming interface
# ---------------------------------------------------------------------------


async def send_message_streaming(user_message: str, history: list):
    """Async generator yielding status and completion events.

    Yields dicts of the form:
        {"type": "status", "message": "..."}
        {"type": "raw_complete", "text": "...", "messages": [...]}
    """
    loop = asyncio.get_event_loop()
    messages = list(history)
    messages.append({"role": "user", "content": [{"text": user_message}]})

    def _converse_sync():
        return _bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": [{"toolSpec": t} for t in TOOLS]},
            inferenceConfig=_INFERENCE_CONFIG,
        )

    for _round in range(_MAX_ROUNDS):
        response = await loop.run_in_executor(None, _converse_sync)

        output_message = response["output"]["message"]
        messages.append(output_message)

        stop_reason = response.get("stopReason", "")

        tool_uses = [
            block
            for block in output_message.get("content", [])
            if "toolUse" in block
        ]

        if not tool_uses or stop_reason == "end_turn":
            text_parts = [
                block["text"]
                for block in output_message.get("content", [])
                if "text" in block
            ]
            full_text = "\n".join(text_parts)
            yield {"type": "raw_complete", "text": full_text, "messages": messages}
            return

        # Dispatch tool calls
        yield {"type": "status", "message": "Querying Snowflake database..."}

        tool_results = []
        for block in tool_uses:
            tool_use = block["toolUse"]

            def _dispatch_sync(name=tool_use["name"], inp=tool_use.get("input", {})):
                return _dispatch_tool(name, inp)

            result_content = await loop.run_in_executor(None, _dispatch_sync)
            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result_content}],
                    }
                }
            )

        messages.append({"role": "user", "content": tool_results})

        if _round < _MAX_ROUNDS - 1:
            yield {"type": "status", "message": "Analyzing results..."}

    # Exceeded max rounds
    last = messages[-1] if messages else {}
    text_parts = [
        block["text"]
        for block in last.get("content", [])
        if isinstance(block, dict) and "text" in block
    ]
    full_text = "\n".join(text_parts) or "I was unable to complete the request."
    yield {"type": "raw_complete", "text": full_text, "messages": messages}
