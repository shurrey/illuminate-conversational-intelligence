# AgentCore to Direct Lambda+Bedrock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 8 always-on AgentCore container runtimes ($5K/mo) with a single Lambda function that calls Bedrock directly, reducing cost to ~$170/mo with no loss in functionality.

**Architecture:** One Lambda function receives user questions, makes a single Claude tool_use call with an `execute_sql` tool. The LLM generates SQL (grounded by the data dictionary in its system prompt), calls `execute_sql` to run it against Snowflake, sees the results, and writes the final response — all in one conversation turn. Conversation memory is stored in DynamoDB instead of AgentCore STM.

**Tech Stack:** AWS Lambda (Python 3.11, LWA streaming), Bedrock `invoke_model_with_response_stream`, DynamoDB, Snowflake, CDK

---

## File Structure

### Files to CREATE
| File | Responsibility |
|------|---------------|
| `chat_engine.py` | Core LLM engine: system prompt, tool definitions, Bedrock invoke_model calls, tool dispatch loop, streaming |
| `conversation_store.py` | DynamoDB conversation memory: load/save/clear message history |
| `cdk/lib/api/conversation-table.ts` | CDK construct for DynamoDB table |

### Files to MODIFY
| File | What changes |
|------|-------------|
| `lambda_handler.py` | Replace `_invoke_orchestrator_*` with `chat_engine` calls. Remove A2A protocol code. Keep all endpoints, auth, markers, PII scrub. |
| `snowflake_client.py` | Add `validate_and_execute(sql, params)` that combines sqlglot AST validation + execution in one call |
| `cdk/lib/api/lambda-proxy.ts` | Remove VPC, remove AgentCore IAM, add Bedrock invoke_model + DynamoDB IAM |
| `cdk/lib/api/index.ts` | Add DynamoDB table construct, pass table name to Lambda |
| `requirements-lambda.txt` | Add `sqlglot`, `boto3` (for DynamoDB). Remove nothing — all existing deps still used. |
| `run.sh` | No change (still `exec python3 lambda_handler.py`) |

### Files to DELETE (after deployment verified)
| File | Why |
|------|-----|
| `agents/` directory (all 8 agents) | No longer deployed as AgentCore runtimes |
| `cdk/lib/agentcore/` directory | AgentCore stack removed |

### Files UNCHANGED
| File | Why |
|------|-----|
| `cdk/lib/base/` | Cognito, S3, Secrets Manager, WAF all stay |
| `verified_queries.json` | Moves into Lambda bundle (still used for short-circuit) |

---

## Task 1: DynamoDB Conversation Store

**Files:**
- Create: `conversation_store.py`
- Create: `cdk/lib/api/conversation-table.ts`
- Modify: `cdk/lib/api/index.ts`

- [ ] **Step 1: Create `conversation_store.py`**

```python
"""
DynamoDB-backed conversation memory.

Stores message history per context_id with automatic TTL expiry.
Replaces AgentCore STM memory at ~$0.25/month instead of AgentCore pricing.
"""
import json
import os
import time
import logging
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("API-PROXY")

_TABLE_NAME = os.environ.get("CONVERSATION_TABLE", "illuminate-conversations-dev")
_TTL_SECONDS = int(os.environ.get("CONVERSATION_TTL", str(30 * 24 * 3600)))  # 30 days
_MAX_MESSAGES = int(os.environ.get("CONVERSATION_MAX_MESSAGES", "50"))

_table = None


def _get_table():
    """Lazy-init DynamoDB Table resource."""
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        _table = dynamodb.Table(_TABLE_NAME)
    return _table


def load_history(context_id: str) -> list[dict]:
    """Load conversation messages for a context_id.

    Returns list of {"role": "user"|"assistant", "content": "..."} dicts,
    ordered chronologically. Returns empty list if no history.
    """
    if not context_id:
        return []
    try:
        table = _get_table()
        response = table.get_item(Key={"context_id": context_id})
        item = response.get("Item")
        if not item:
            return []
        messages = json.loads(item.get("messages", "[]"))
        return messages[-_MAX_MESSAGES:]
    except Exception as e:
        logger.warning(f"Failed to load conversation history: {e}")
        return []


def save_turn(context_id: str, user_message: str, assistant_message: str):
    """Append a user+assistant turn to conversation history.

    Creates the item if it doesn't exist, appends if it does.
    Trims to MAX_MESSAGES and sets TTL for automatic cleanup.
    """
    if not context_id:
        return
    try:
        history = load_history(context_id)
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": assistant_message})
        # Trim to max
        history = history[-_MAX_MESSAGES:]

        table = _get_table()
        table.put_item(Item={
            "context_id": context_id,
            "messages": json.dumps(history),
            "updated_at": int(time.time()),
            "ttl": int(time.time()) + _TTL_SECONDS,
        })
    except Exception as e:
        logger.warning(f"Failed to save conversation history: {e}")


def clear_history(context_id: str):
    """Delete conversation history for a context_id."""
    if not context_id:
        return
    try:
        table = _get_table()
        table.delete_item(Key={"context_id": context_id})
    except Exception as e:
        logger.warning(f"Failed to clear conversation history: {e}")
```

- [ ] **Step 2: Create `cdk/lib/api/conversation-table.ts`**

```typescript
import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

export interface ConversationTableProps {
  environment: string;
}

export class ConversationTable extends Construct {
  public readonly table: dynamodb.Table;
  public readonly tableName: string;

  constructor(scope: Construct, id: string, props: ConversationTableProps) {
    super(scope, id);

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `illuminate-conversations-${props.environment}`,
      partitionKey: { name: 'context_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.tableName = this.table.tableName;
  }
}
```

- [ ] **Step 3: Wire DynamoDB table into ApiStack**

Read `cdk/lib/api/index.ts` and add the ConversationTable construct. Pass `tableName` to the Lambda environment. Add DynamoDB permissions to Lambda role.

In `cdk/lib/api/index.ts`, after other imports add:
```typescript
import { ConversationTable } from './conversation-table';
```

In the constructor, before the LambdaProxy construct:
```typescript
const conversationTable = new ConversationTable(this, 'ConversationTable', {
  environment: props.environment,
});
```

Pass to Lambda environment: `CONVERSATION_TABLE: conversationTable.tableName`

Add IAM permission to Lambda role in `lambda-proxy.ts`:
```typescript
// DynamoDB conversation memory
role.addToPolicy(new iam.PolicyStatement({
  actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem'],
  resources: [/* table ARN passed as prop */],
}));
```

- [ ] **Step 4: Verify CDK compiles**

Run: `cd cdk && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add conversation_store.py cdk/lib/api/conversation-table.ts cdk/lib/api/index.ts
git commit -m "feat: add DynamoDB conversation store to replace AgentCore STM"
```

---

## Task 2: Chat Engine — Core LLM with Tool Use

This is the main module that replaces 8 AgentCore agents with a single Bedrock `invoke_model` call using Claude's tool_use feature.

**Files:**
- Create: `chat_engine.py`
- Modify: `snowflake_client.py` (add `validate_and_execute`)
- Modify: `requirements-lambda.txt` (add `sqlglot`)

- [ ] **Step 1: Add sqlglot to Lambda dependencies**

In `requirements-lambda.txt`, add:
```
sqlglot>=26.0.0
```

- [ ] **Step 2: Add `validate_and_execute` to `snowflake_client.py`**

This combines the sqlglot AST validation from the SQL agent with query execution. Add after the existing `query_sql` function:

```python
def validate_and_execute(sql: str, params: dict | None = None) -> dict:
    """Validate SQL via AST parsing, then execute if safe.

    Blocks DML/DDL, enforces CDM_* schema whitelist, checks PII columns,
    enforces row limits. Returns results or error dict.

    Returns:
        {"columns": [...], "rows": [...]} on success
        {"error": "..."} on validation failure or execution error
    """
    import sqlglot
    from sqlglot import exp

    query_stripped = sql.strip()
    query_upper = query_stripped.upper()

    # Allow SHOW/DESCRIBE through with basic safety check
    if query_upper.startswith(("SHOW", "DESCRIBE", "DESC")):
        if ";" in query_stripped[4:]:
            return {"error": "Multiple statements are not allowed."}
        return query_sql(query_stripped, params)

    # Full AST validation for SELECT/WITH queries
    try:
        statements = sqlglot.parse(query_stripped, dialect="snowflake")
    except sqlglot.errors.ParseError as e:
        return {"error": f"SQL parse error: {e}"}

    if not statements:
        return {"error": "Empty SQL query."}

    if len(statements) > 1:
        return {"error": "Multiple SQL statements are not allowed."}

    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.Command)):
        return {"error": f"Only SELECT/WITH queries are allowed. Got: {type(stmt).__name__}"}

    if isinstance(stmt, exp.Command):
        cmd = str(stmt.this).upper()
        if cmd in ("SHOW", "DESCRIBE", "DESC"):
            return query_sql(query_stripped, params)
        return {"error": f"Command '{cmd}' is not allowed."}

    # Block DML/DDL hidden in subqueries
    for node in stmt.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter)):
            return {"error": f"{type(node).__name__} operations are not allowed."}

    # Schema whitelist — only CDM_* and INFORMATION_SCHEMA
    ALLOWED_PREFIXES = ("CDM_",)
    for table in stmt.find_all(exp.Table):
        schema_name = table.db
        if schema_name:
            schema_upper = schema_name.upper()
            if not any(schema_upper.startswith(p) for p in ALLOWED_PREFIXES):
                if schema_upper not in ("INFORMATION_SCHEMA",):
                    return {"error": f"Schema '{schema_name}' is not allowed. Only CDM_* schemas are permitted."}

    # PII column check in outermost SELECT without aggregation
    PII_COLUMNS = frozenset({
        "FIRST_NAME", "LAST_NAME", "MIDDLE_NAME", "EMAIL", "EMAIL_ADDRESS",
        "SSN", "SOCIAL_SECURITY_NUMBER", "PHONE", "PHONE_NUMBER", "MOBILE_PHONE",
        "HOME_PHONE", "ADDRESS", "STREET_ADDRESS", "MAILING_ADDRESS",
        "DATE_OF_BIRTH", "DOB", "BIRTH_DATE", "STUDENT_NAME", "FULL_NAME",
        "USERNAME", "LOGIN_ID", "PASSWORD",
    })
    select_columns = set()
    for col_expr in stmt.find_all(exp.Column):
        parent_select = col_expr.find_ancestor(exp.Select)
        if parent_select is stmt:
            col_name = col_expr.name.upper() if col_expr.name else ""
            select_columns.add(col_name)

    pii_in_select = select_columns & PII_COLUMNS
    if pii_in_select:
        has_group_by = stmt.find(exp.Group) is not None
        has_agg = any(isinstance(n, (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)) for n in stmt.walk())
        if not (has_group_by or has_agg):
            return {"error": f"FERPA violation — PII columns ({', '.join(sorted(pii_in_select))}) without aggregation."}

    # Enforce LIMIT <= 1000
    MAX_ROWS = 1000
    limit_node = stmt.find(exp.Limit)
    if limit_node:
        try:
            limit_val = int(limit_node.expression.this)
            if limit_val > MAX_ROWS:
                return {"error": f"LIMIT {limit_val} exceeds maximum of {MAX_ROWS}."}
        except (ValueError, AttributeError):
            pass

    # Validation passed — execute
    try:
        return query_sql(query_stripped, params)
    except Exception as e:
        return {"error": str(e)}
```

- [ ] **Step 3: Create `chat_engine.py`**

This is the core module. It:
1. Fetches the data dictionary at import time (startup)
2. Builds a system prompt with the full schema reference
3. Defines `execute_sql` as a Claude tool
4. Calls Bedrock `invoke_model_with_response_stream` with tool_use
5. Dispatches tool calls to Snowflake
6. Returns the final response with streaming support

```python
"""
Chat engine — single-LLM architecture replacing 8 AgentCore agents.

Makes one Claude call with tool_use. The LLM generates SQL (grounded by
the data dictionary), executes it via the execute_sql tool, and writes
the final response — all in one conversation turn.
"""
import json
import logging
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import boto3

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

# Bedrock runtime client (created once at module load)
_bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# ---------------------------------------------------------------------------
# Data Dictionary (fetched once at startup)
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_DICT_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _fetch_data_dictionary() -> tuple:
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


def _compile_schema_reference(submodels, definitions, erd) -> str:
    """Compile data dictionary into compact schema reference for the system prompt."""
    def_index = {}
    for d in definitions:
        fqn = d.get("name", "")
        if fqn:
            def_index[fqn.upper()] = d

    schema_names = {}
    for s in submodels:
        schema_names[s.get("schemaId", "").upper()] = s.get("displayName", s.get("name", ""))

    lines = []
    for schema_block in erd.get("schemas", []):
        tables = schema_block.get("tables", [])
        if not tables:
            continue
        first_fqn = tables[0].get("FQN", "")
        schema_id = first_fqn.split(".")[0].upper() if "." in first_fqn else "UNKNOWN"
        display_name = schema_names.get(schema_id, schema_id)
        is_priority = schema_id in _PRIORITY_SCHEMAS

        lines.append(f"\n## {schema_id} ({display_name})")
        if not is_priority:
            table_names = [t.get("FQN", "").split(".")[-1] for t in tables]
            lines.append(f"Tables: {', '.join(table_names)}")
            lines.append("Use execute_sql with DESCRIBE TABLE for column details if needed.")
            continue

        for table in tables:
            table_fqn = table.get("FQN", "")
            table_name = table_fqn.split(".")[-1] if "." in table_fqn else table_fqn
            lines.append(f"\n### {table_name}")
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
                lines.append(f"  {col_name} {data_type}{flag_str}{desc_short}")

        fks = schema_block.get("foreignKeys", [])
        if fks:
            lines.append(f"\nRelationships in {schema_id}:")
            for fk in fks:
                fk_info = fk.get("foreignKey", {})
                uk_info = fk.get("uniqueKey", {})
                fk_cols = ".".join(c["name"] for c in fk_info.get("columns", []))
                uk_table = uk_info.get("tableFQN", "")
                uk_cols = ".".join(c["name"] for c in uk_info.get("columns", []))
                lines.append(f"  {fk_info.get('tableFQN','')}.{fk_cols} → {uk_table}.{uk_cols}")

    return "\n".join(lines)


# Fetch at startup
_compiled_schema = ""
_dictionary_loaded = False
try:
    logger.info("Fetching data dictionary ...")
    _submodels, _definitions, _erd = _fetch_data_dictionary()
    _compiled_schema = _compile_schema_reference(_submodels, _definitions, _erd)
    _dictionary_loaded = True
    logger.info(f"Data dictionary loaded: {len(_compiled_schema)} chars")
except Exception as e:
    logger.warning(f"Data dictionary fetch failed: {e}")
    _compiled_schema = "Data dictionary unavailable. Use execute_sql with DESCRIBE TABLE to discover schema."


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
_database = os.environ.get("SNOWFLAKE_DATABASE", "")
if not _database:
    # Try to get from Secrets Manager
    try:
        _sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        _secret = json.loads(
            _sm.get_secret_value(
                SecretId=os.environ.get("SNOWFLAKE_SECRET_NAME", "illuminate/dev/snowflake")
            )["SecretString"]
        )
        _database = _secret.get("database", "YOUR_DATABASE")
    except Exception:
        _database = "YOUR_DATABASE"

SYSTEM_PROMPT = f"""You are Illuminate, an AI assistant for educational data analytics.
You help university administrators and institutional researchers query and understand
their Blackboard Learn data stored in a Snowflake data warehouse.

## Your Capabilities
1. Generate and execute SQL queries against Snowflake using the execute_sql tool
2. Analyze query results and identify trends, patterns, and insights
3. Present findings in clear, actionable language for educational administrators
4. Create chart configurations for data visualization
5. Ensure FERPA compliance — never expose individual student data

## Database Configuration
The Snowflake database is: {_database}
You MUST use fully qualified table names: {_database}.CDM_LMS.TABLE_NAME

## Complete Data Dictionary (AUTHORITATIVE)
The following is the definitive schema reference. Use ONLY column names listed here.
Do NOT guess or assume column names exist — if a column is not listed, it does not exist.

{_compiled_schema}

## Query Guidelines
1. ALWAYS use fully qualified table names: {_database}.CDM_LMS.TABLE_NAME
2. Use ONLY column names from the Data Dictionary — never invent columns
3. Use FK relationships from the dictionary for JOINs (e.g., COURSE.TERM_ID → TERM.ID)
4. Primary keys are always ID on each table (not TABLE_NAME_ID)
5. Use LIMIT to avoid returning too many rows (default LIMIT 100)
6. For aggregations, include meaningful GROUP BY clauses
7. Student enrollments: filter PERSON_COURSE.COURSE_ROLE = 'S'
8. Instructor enrollments: filter PERSON_COURSE.COURSE_ROLE = 'I'

## FERPA Compliance (CRITICAL)
- NEVER return individual student names, emails, SSNs, or personal identifiers
- Columns marked [PII] in the dictionary must NEVER appear in SELECT without aggregation
- Always AGGREGATE student data (minimum 5 individuals per group)
- Use PERSON_ID only for JOINs, never expose it in final results

## Workflow
1. Generate the SQL query using the data dictionary for correct table/column names
2. Execute using the execute_sql tool
3. If the query fails, read the error, fix the SQL, and retry ONCE
4. Analyze the results and present insights
5. Include a [CHART_CONFIG] block if a visualization would be helpful

## Parameterized Queries
When a query needs user-specific input that was NOT provided in the question:
- Use Snowflake bind variable syntax (:param_name) in the SQL
- Include a [QUERY_PARAMS] block after the [SQL_QUERY] block
- Explain what input is needed

## Visualizations
When data is suited for a chart, include:

[CHART_CONFIG]
{{"chart_type": "bar|line|pie|scatter|histogram", "title": "...", "x_axis": "key", "y_axis": "key", "data": [...]}}
[/CHART_CONFIG]

The data array MUST contain actual query results, never placeholder data.

## SQL Transparency
Always include executed SQL in your response:

[SQL_QUERY]
{{"title": "Brief description", "sql": "SELECT ..."}}
[/SQL_QUERY]

## Response Style
- Be concise and actionable
- Lead with the key finding, then supporting data
- Use markdown tables for data
- Suggest follow-up questions when appropriate
- For educational administrators — avoid jargon, focus on institutional impact"""


# ---------------------------------------------------------------------------
# Tool Definitions (Claude tool_use format)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "execute_sql",
        "description": (
            "Execute a read-only SQL query against the Snowflake data warehouse. "
            "Only SELECT, WITH, SHOW, and DESCRIBE statements are allowed. "
            "The query is validated for safety (no DML/DDL, schema whitelist, PII checks) "
            "before execution. Returns columns and rows as JSON, or an error message. "
            "Supports Snowflake bind variables via the params dict (:name syntax)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute. Must be SELECT, WITH, SHOW, or DESCRIBE.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional bind variable values. Keys are parameter names (without colon prefix), values are strings or numbers.",
                    "additionalProperties": True,
                },
            },
            "required": ["sql"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Dispatch
# ---------------------------------------------------------------------------
def _dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return the result as a string."""
    if tool_name == "execute_sql":
        from snowflake_client import validate_and_execute
        sql = tool_input.get("sql", "")
        params = tool_input.get("params")
        result = validate_and_execute(sql, params)
        if "error" in result:
            return f"ERROR: {result['error']}"
        # Format as compact JSON for the LLM (not markdown — LLM will format)
        return json.dumps(result, default=str)
    else:
        return f"ERROR: Unknown tool '{tool_name}'"


# ---------------------------------------------------------------------------
# Bedrock Converse API
# ---------------------------------------------------------------------------
def send_message(
    user_message: str,
    history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Send a message to Claude via Bedrock and return (response_text, updated_history).

    Handles the tool_use loop: if Claude requests a tool call, dispatches it
    and feeds the result back until Claude produces a final text response.

    Args:
        user_message: The user's question.
        history: Prior conversation messages in Bedrock Converse format.

    Returns:
        (assistant_text, updated_history) — the final text and full message list.
    """
    messages = list(history or [])
    messages.append({
        "role": "user",
        "content": [{"text": user_message}],
    })

    # Tool-use loop: call Bedrock, dispatch tools, repeat until text response
    max_rounds = 5
    for _ in range(max_rounds):
        response = _bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": [{"toolSpec": t} for t in TOOLS]},
            inferenceConfig={"temperature": 0.0, "maxTokens": 4096},
        )

        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        # Check if there are tool_use blocks
        tool_uses = [
            block for block in assistant_message["content"]
            if "toolUse" in block
        ]

        if not tool_uses:
            # No tool calls — extract text and return
            text_parts = [
                block["text"] for block in assistant_message["content"]
                if "text" in block
            ]
            return "\n".join(text_parts), messages

        # Dispatch tool calls and build toolResult message
        tool_results = []
        for block in tool_uses:
            tu = block["toolUse"]
            logger.info(f"Tool call: {tu['name']}({json.dumps(tu['input'])[:200]})")
            result_str = _dispatch_tool(tu["name"], tu["input"])
            tool_results.append({
                "toolResult": {
                    "toolUseId": tu["toolUseId"],
                    "content": [{"text": result_str}],
                }
            })

        messages.append({"role": "user", "content": tool_results})

    # Exhausted rounds — return whatever we have
    return "I was unable to complete the request within the allowed steps.", messages


async def send_message_streaming(
    user_message: str,
    history: list[dict] | None = None,
):
    """Stream a response from Claude via Bedrock Converse Stream API.

    Yields frontend events:
    - {"type": "status", "message": "..."}
    - {"type": "text_delta", "text": "..."}
    - {"type": "complete", "data": {"text": ..., "artifacts": [...], "contextId": ...}}

    Handles tool_use loop internally — streams status updates during tool execution
    and streams the final text response token-by-token.
    """
    import asyncio

    messages = list(history or [])
    messages.append({
        "role": "user",
        "content": [{"text": user_message}],
    })

    loop = asyncio.get_event_loop()
    max_rounds = 5
    full_text = ""

    for round_num in range(max_rounds):
        # Call Bedrock in a thread (boto3 is sync)
        def _call_bedrock():
            return _bedrock.converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig={"tools": [{"toolSpec": t} for t in TOOLS]},
                inferenceConfig={"temperature": 0.0, "maxTokens": 4096},
            )

        yield {"type": "status", "message": "Thinking..."}
        response = await loop.run_in_executor(None, _call_bedrock)

        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        tool_uses = [b for b in assistant_message["content"] if "toolUse" in b]

        if not tool_uses:
            # Final text response
            text_parts = [b["text"] for b in assistant_message["content"] if "text" in b]
            full_text = "\n".join(text_parts)
            break

        # Dispatch tools
        tool_results = []
        for block in tool_uses:
            tu = block["toolUse"]
            tool_name = tu["name"]
            yield {"type": "status", "message": "Querying Snowflake database..."}
            logger.info(f"Tool call: {tool_name}({json.dumps(tu['input'])[:200]})")
            result_str = await loop.run_in_executor(
                None, lambda t=tu: _dispatch_tool(t["name"], t["input"])
            )
            tool_results.append({
                "toolResult": {
                    "toolUseId": tu["toolUseId"],
                    "content": [{"text": result_str}],
                }
            })

        messages.append({"role": "user", "content": tool_results})

        if round_num < max_rounds - 1:
            yield {"type": "status", "message": "Analyzing results..."}

    if not full_text:
        full_text = "I was unable to complete the request within the allowed steps."

    # Return complete event (markers will be extracted by lambda_handler)
    yield {"type": "raw_complete", "text": full_text, "messages": messages}
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('chat_engine.py').read()); print('OK')"`
Expected: `OK`

Run: `python3 -c "import ast; ast.parse(open('snowflake_client.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add chat_engine.py snowflake_client.py requirements-lambda.txt
git commit -m "feat: add chat_engine with single-LLM Bedrock tool_use architecture"
```

---

## Task 3: Rewire Lambda Handler

Replace the AgentCore A2A invocation code in `lambda_handler.py` with calls to `chat_engine`. Keep all existing endpoints, auth, marker extraction, PII scrub, and streaming infrastructure.

**Files:**
- Modify: `lambda_handler.py`

- [ ] **Step 1: Replace the A2A client and orchestrator functions**

Remove these sections from `lambda_handler.py`:
- The `_agentcore_boto3` client creation (around line 352-361)
- `_build_a2a_request` function
- `_invoke_orchestrator_sync` function
- `_invoke_orchestrator_stream` function
- `_extract_text_from_result` function

Replace `send_message` with:

```python
async def send_message(message_text: str, context_id: Optional[str] = None) -> dict:
    """Send a message via chat_engine (non-streaming)."""
    from chat_engine import send_message as engine_send
    from conversation_store import load_history, save_turn

    history = load_history(context_id) if context_id else []
    # Convert our simple format to Bedrock Converse format
    bedrock_history = []
    for msg in history:
        bedrock_history.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })

    response_text, _ = engine_send(message_text, bedrock_history)

    # Save conversation turn
    if context_id:
        save_turn(context_id, message_text, response_text)

    return {"text": response_text, "contextId": context_id}
```

Replace `send_message_streaming` with:

```python
async def send_message_streaming(message_text: str, context_id: Optional[str] = None):
    """Stream a response via chat_engine, yielding frontend events."""
    from chat_engine import send_message_streaming as engine_stream
    from conversation_store import load_history, save_turn

    yield {"type": "status", "message": "Processing your question..."}

    history = load_history(context_id) if context_id else []
    bedrock_history = []
    for msg in history:
        bedrock_history.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })

    full_text = ""
    try:
        async for event in engine_stream(message_text, bedrock_history):
            if event["type"] == "status":
                yield event
            elif event["type"] == "raw_complete":
                full_text = event["text"]
                # Save conversation
                if context_id:
                    save_turn(context_id, message_text, full_text)

        if not full_text:
            yield {"type": "error", "message": "Empty response"}
            return

        # Process markers (same as before)
        cleaned_text, chart_artifacts = extract_chart_configs(full_text)
        cleaned_text, sql_artifacts = extract_sql_queries(cleaned_text)
        artifacts = chart_artifacts + sql_artifacts
        cleaned_text = _scrub_pii(cleaned_text)

        yield {
            "type": "complete",
            "data": {
                "text": cleaned_text,
                "artifacts": artifacts,
                "contextId": context_id,
            },
        }

    except Exception as e:
        logger.error(f"Chat engine error: {e}")
        yield {"type": "error", "message": str(e)}
```

- [ ] **Step 2: Update the sync chat endpoint**

In the `POST /api/chat` handler, update the response processing to work with the new return format (it now returns `{"text": ..., "contextId": ...}` directly instead of A2A format):

```python
result = await send_message(message_text=message_text, context_id=context_id)
text = result.get("text", "")

# Extract markers
cleaned_text, chart_artifacts = extract_chart_configs(text)
cleaned_text, sql_artifacts = extract_sql_queries(cleaned_text)
artifacts = chart_artifacts + sql_artifacts
cleaned_text = _scrub_pii(cleaned_text)

return ChatResponse(
    text=cleaned_text,
    artifacts=artifacts,
    context_id=result.get("contextId", context_id),
)
```

- [ ] **Step 3: Update conversation endpoints**

Update `GET /api/conversations/{context_id}` to load from DynamoDB:

```python
@app.get("/api/conversations/{context_id}")
async def get_conversation(context_id: str, authorization: str = Header(...)):
    user = _get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    from conversation_store import load_history
    history = load_history(context_id)
    return {"messages": history}
```

Update `DELETE /api/conversations/{context_id}`:

```python
@app.delete("/api/conversations/{context_id}")
async def clear_conversation(context_id: str, authorization: str = Header(...)):
    user = _get_user_from_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    from conversation_store import clear_history
    clear_history(context_id)
    return {"success": True}
```

- [ ] **Step 4: Remove dead code**

Remove these now-unused items from `lambda_handler.py`:
- `_TOOL_STATUS_MESSAGES` dict (status messages now come from chat_engine)
- `strip_tool_status_markers` function
- `_TOOL_STATUS_PATTERN` regex
- `ORCHESTRATOR_ARN` env var reference
- `_ensure_orchestrator_configured` function

Keep:
- All auth code (JWT validation, Cognito JWKS)
- All marker extraction (charts, SQL queries, query params)
- PII scrub
- All data dictionary proxy endpoints
- Dashboard query endpoint
- Snowflake config endpoints
- CORS, FastAPI app setup

- [ ] **Step 5: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('lambda_handler.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add lambda_handler.py
git commit -m "feat: rewire Lambda to use chat_engine instead of AgentCore orchestrator"
```

---

## Task 4: Update CDK — Remove AgentCore, Simplify Lambda

**Files:**
- Modify: `cdk/lib/api/lambda-proxy.ts` (remove VPC, update IAM)
- Modify: `cdk/lib/api/index.ts` (add DynamoDB, remove AgentCore dependency)
- Modify: `cdk/bin/illuminate.ts` (remove AgentCore stack)

- [ ] **Step 1: Update `lambda-proxy.ts`**

Key changes:
- Remove `vpc`, `securityGroup`, `vpcSubnets` from Lambda function
- Remove `orchestratorArn` from props and env vars
- Remove AgentCore IAM permission (`bedrock-agentcore:InvokeAgentRuntime`)
- Remove VPC managed policy
- Add Bedrock model invocation IAM:
```typescript
role.addToPolicy(new iam.PolicyStatement({
  actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
  resources: [
    'arn:aws:bedrock:*::foundation-model/anthropic.claude-*',
    `arn:aws:bedrock:*:${cdk.Aws.ACCOUNT_ID}:inference-profile/us.anthropic.claude-*`,
  ],
}));
```
- Add DynamoDB IAM (receives table ARN as prop):
```typescript
role.addToPolicy(new iam.PolicyStatement({
  actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem'],
  resources: [props.conversationTableArn],
}));
```
- Add `CONVERSATION_TABLE` and `BEDROCK_MODEL_ID` to Lambda environment
- Remove `ILLUMINATE_USE_A2A`, `ORCHESTRATOR_ARN`, `A2A_TIMEOUT` env vars
- Update bundling command to also copy `chat_engine.py`, `conversation_store.py`, and `agents/sql/verified_queries.json`:
```typescript
command: [
  'bash', '-c', [
    'pip install -q -t /asset-output --platform manylinux2014_x86_64 --implementation cp --python-version 3.11 --only-binary=:all: -r requirements-lambda.txt',
    'cp lambda_handler.py chat_engine.py conversation_store.py snowflake_client.py run.sh /asset-output/',
    'cp agents/sql/verified_queries.json /asset-output/',
  ].join(' && '),
],
```

- [ ] **Step 2: Update `cdk/lib/api/index.ts`**

Read the current file. Changes:
- Import `ConversationTable`
- Create the DynamoDB table construct
- Remove references to AgentCore stack outputs (orchestratorArn)
- Pass `conversationTableArn` and `conversationTableName` to LambdaProxy
- Remove VPC/securityGroup props if they were only for AgentCore access

- [ ] **Step 3: Update `cdk/bin/illuminate.ts`**

Read the current file. Remove the `AgentCoreStack` instantiation entirely. The ApiStack should no longer depend on AgentCoreStack. It still depends on BaseStack (for Cognito, Secrets Manager).

- [ ] **Step 4: Verify CDK compiles**

Run: `cd cdk && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add cdk/
git commit -m "feat: remove AgentCore CDK stack, add DynamoDB, simplify Lambda"
```

---

## Task 5: Deploy and Verify

- [ ] **Step 1: CDK diff to verify changes**

Run: `cd cdk && npx cdk diff`

Expected: Shows removal of AgentCore resources, addition of DynamoDB table, Lambda function update. No changes to BaseStack (Cognito, S3, Secrets stay).

- [ ] **Step 2: Deploy**

Run: `cd cdk && npx cdk deploy --all --require-approval never`

This will:
- Create the DynamoDB conversation table
- Update the Lambda function (new code, new IAM, no VPC)
- The AgentCore stack will still exist but can be deleted manually after verification

- [ ] **Step 3: Test simple query**

```bash
curl -X POST "https://<function-url>/api/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "How many students are there?"}'
```

Expected: Response with student count, SQL artifact.

- [ ] **Step 4: Test streaming**

```bash
curl -N "https://<function-url>/api/chat/stream" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "Show enrollment counts by term"}'
```

Expected: SSE events with status updates, then complete event with data.

- [ ] **Step 5: Test conversation memory**

Send two messages with the same context_id. Second message should reference the first.

- [ ] **Step 6: Test parameterized query**

Ask a question that requires user input. Verify the response includes `parameters` array on the SQL artifact.

- [ ] **Step 7: Delete AgentCore stack (after all tests pass)**

Run: `cd cdk && npx cdk destroy IlluminateAgentCore-dev`

This removes all 8 AgentCore runtimes, the keep-warm Lambda, the STM memory, and the FERPA guardrail. The cost savings begin immediately.

- [ ] **Step 8: Commit final state**

```bash
git add -A
git commit -m "chore: deploy verified — AgentCore removed, single-Lambda architecture live"
```

---

## Task 6: Cleanup — Remove Agent Source Code

After deployment is verified and AgentCore stack is destroyed.

**Files:**
- Delete: `agents/` directory (all 8 agent directories)

- [ ] **Step 1: Move verified_queries.json to project root**

The verified queries file is still useful and is now bundled directly into Lambda.

```bash
cp agents/sql/verified_queries.json ./verified_queries.json
```

Update the bundling command in `lambda-proxy.ts` to reference the new location.

- [ ] **Step 2: Delete agents directory**

```bash
rm -rf agents/
```

- [ ] **Step 3: Remove AgentCore CDK code**

```bash
rm -rf cdk/lib/agentcore/
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove AgentCore agent source and CDK code"
```
