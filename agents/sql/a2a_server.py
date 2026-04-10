#!/usr/bin/env python3
"""
SQL Agent - Self-contained A2A server for AgentCore deployment.

Uses bedrock_agentcore.runtime.a2a.build_a2a_app() to create a Starlette app
with proper /ping and A2A routes for AgentCore.

The `app` object is exposed at module level so that AgentCore's runtime can
import it (e.g., `uvicorn a2a_server:app`).
"""
import json
import os
import sys
from pathlib import Path


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def load_snowflake_credentials():
    """Load Snowflake credentials from AWS Secrets Manager."""
    secret_name = os.environ.get("SNOWFLAKE_SECRET_NAME", "illuminate/dev/snowflake")
    region = os.environ.get("AWS_REGION", "us-east-1")

    if all(os.environ.get(k) for k in ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]):
        log("  Snowflake credentials already set via environment")
        return

    log(f"  Loading from Secrets Manager: {secret_name}")
    import boto3
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response["SecretString"])

    env_map = {
        "SNOWFLAKE_ACCOUNT": ["account", "SNOWFLAKE_ACCOUNT"],
        "SNOWFLAKE_USER": ["user", "username", "SNOWFLAKE_USER"],
        "SNOWFLAKE_PASSWORD": ["password", "SNOWFLAKE_PASSWORD"],
        "SNOWFLAKE_DATABASE": ["database", "SNOWFLAKE_DATABASE"],
        "SNOWFLAKE_WAREHOUSE": ["warehouse", "SNOWFLAKE_WAREHOUSE"],
        "SNOWFLAKE_ROLE": ["role", "SNOWFLAKE_ROLE"],
    }

    for env_var, possible_keys in env_map.items():
        if env_var not in os.environ:
            for key in possible_keys:
                if key in secret:
                    os.environ[env_var] = str(secret[key])
                    break

    set_vars = [k for k in env_map if os.environ.get(k)]
    log(f"  Credentials loaded: {set_vars}")


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

log("Loading Snowflake credentials ...")
load_snowflake_credentials()

log("Importing dependencies ...")
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from bedrock_agentcore.runtime.a2a import build_a2a_app

# --- Snowflake connection (lazy) ---
_sf_connection = None


def get_snowflake_connection():
    """Get or create Snowflake connection (lazy init)."""
    global _sf_connection
    if _sf_connection is None or _sf_connection.is_closed():
        import snowflake.connector
        _sf_connection = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            database=os.environ.get("SNOWFLAKE_DATABASE", ""),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
            role=os.environ.get("SNOWFLAKE_ROLE", ""),
        )
    return _sf_connection


# --- System Prompt ---
database = os.environ.get("SNOWFLAKE_DATABASE", "YOUR_DATABASE")

SQL_SYSTEM_PROMPT = f"""You are the SQL Agent for an educational data analytics system.
Your ONLY job is to generate and execute SQL queries. You do NOT analyze or interpret results.

## Your Role
1. Understand what data the user needs
2. Generate accurate SQL queries
3. Execute queries using the available Snowflake tools
4. Return the raw data

## IMPORTANT: Database Configuration
The Snowflake database is: {database}
You MUST use fully qualified table names: {database}.CDM_LMS.TABLE_NAME

## Available Tools
- **lookup_verified_query**: ALWAYS check this FIRST for pre-validated SQL matching the question
- **list_objects**: Discover available schemas and tables
- **describe_object**: Get column information for a specific table
- **run_snowflake_query**: Execute SQL SELECT queries

## Workflow (MUST FOLLOW)
1. ALWAYS start with lookup_verified_query to check for a pre-validated query
2. If a verified query is found, you MUST use its exact tables and columns — only add WHERE filters for specific values the user mentioned
3. NEVER substitute different tables or columns when a verified query is available
4. If no match found, use list_objects/describe_object to discover schema, then write custom SQL
5. Execute with run_snowflake_query

## Query Guidelines
1. ALWAYS use fully qualified table names: {database}.CDM_LMS.TABLE_NAME
2. Use the EXACT column names from describe_object results
3. Use LIMIT to avoid returning too many rows (default LIMIT 100)
4. For aggregations, include meaningful GROUP BY clauses
5. Use JOINs when queries span multiple tables

## GPA Calculations (CRITICAL)
- ALWAYS use the GRADE_NUMERIC column for GPA calculations — it is on a 4.0 scale
- NEVER use normalized score columns (0-1 scale) for GPA — they are NOT GPA values
- Filter with WHERE GRADE_NUMERIC IS NOT NULL to exclude ungraded records

## FERPA Compliance (CRITICAL)
- NEVER return individual student names, emails, SSNs, or personal identifiers
- Always AGGREGATE student data (minimum 5 individuals per group)
- Use PERSON_ID only for JOINs, never expose it in final results

## Response Guidelines
1. Briefly explain what query you're running
2. Execute the query using run_snowflake_query
3. Present the raw results in a markdown table
4. Do NOT analyze, interpret, or provide insights - that's the Analyst's job

## IMPORTANT: Data Format
ALWAYS present query results as a markdown table:

| Column1 | Column2 | Column3 |
|---------|---------|---------|
| value1  | value2  | value3  |

Include ALL result rows (up to LIMIT).
Keep your response focused on the data, not interpretation."""


# --- Verified Query Library ---
_verified_queries = []
_verified_queries_path = Path(__file__).parent / "verified_queries.json"
if _verified_queries_path.exists():
    try:
        _verified_queries = json.loads(_verified_queries_path.read_text())
        # Replace {database} placeholder with actual database name
        for q in _verified_queries:
            q["sql"] = q["sql"].replace("{database}", database)
        log(f"Loaded {len(_verified_queries)} verified queries")
    except Exception as e:
        log(f"WARNING: Failed to load verified queries: {e}")


def _score_query_match(question_lower: str, entry: dict) -> float:
    """Score how well a verified query matches the question. Uses both phrase and word overlap."""
    score = 0.0
    question_words = set(question_lower.split())

    for keyword in entry["keywords"]:
        # Exact phrase match (high value)
        if keyword in question_lower:
            score += len(keyword.split()) * 2.0
        else:
            # Word overlap scoring — how many words in the keyword appear in the question
            keyword_words = set(keyword.split())
            overlap = question_words & keyword_words
            if len(overlap) >= max(1, len(keyword_words) * 0.5):
                score += len(overlap) * 0.5

    # Bonus for intent word overlap
    intent_words = set(entry["intent"].lower().split())
    intent_overlap = question_words & intent_words
    score += len(intent_overlap) * 0.3

    return score


# Term name patterns for auto-substitution in verified queries
import re as _re
_TERM_PATTERN = _re.compile(
    r'(fall|spring|summer|winter|autumn)\s+(20\d{2})',
    _re.IGNORECASE,
)


def _extract_term_filter(question: str) -> str | None:
    """Extract a term name like 'Fall 2024' from the question."""
    match = _TERM_PATTERN.search(question)
    if match:
        return f"{match.group(1).capitalize()} {match.group(2)}"
    return None


@tool
def lookup_verified_query(question: str) -> str:
    """Search the verified query library for a pre-validated SQL query matching the user's question.

    Use this tool FIRST before writing custom SQL. If a verified query is found and can be
    executed directly, this tool will execute it and return results — no further SQL generation
    needed. If the query needs modification beyond what auto-substitution can handle, it returns
    the template for you to adapt.

    Args:
        question: The user's natural language question about the data.

    Returns:
        Either query results (if auto-executed) or a verified SQL template to use.
    """
    if not _verified_queries:
        return "No verified queries available. Generate SQL manually."

    question_lower = question.lower()
    matches = []

    for entry in _verified_queries:
        score = _score_query_match(question_lower, entry)
        if score > 0:
            matches.append((score, entry))

    if not matches:
        return "No verified query found for this question. Generate SQL manually."

    # Return the best match
    matches.sort(key=lambda x: x[0], reverse=True)
    best = matches[0][1]
    sql = best["sql"]

    # Auto-substitute term name if the query has a <TERM_NAME> placeholder
    term_name = _extract_term_filter(question)
    if "<TERM_NAME>" in sql and term_name:
        sql = sql.replace("<TERM_NAME>", term_name)

    # If the query is ready to execute (no remaining placeholders), run it directly
    if "<" not in sql:
        # For term-specific queries where user specified a term but the verified
        # query doesn't have a placeholder, add a WHERE filter
        if term_name and "TERM" in sql.upper() and term_name.lower() not in sql.lower():
            # Add term filter to the query
            if "WHERE" in sql.upper():
                sql = _re.sub(
                    r'(WHERE\s)',
                    f"\\1t.NAME ILIKE '%{term_name}%' AND ",
                    sql,
                    count=1,
                    flags=_re.IGNORECASE,
                )
            elif "GROUP BY" in sql.upper():
                sql = _re.sub(
                    r'(GROUP BY)',
                    f"WHERE t.NAME ILIKE '%{term_name}%' \\1",
                    sql,
                    count=1,
                    flags=_re.IGNORECASE,
                )

        # Execute the verified query directly
        log(f"  Auto-executing verified query: {best['intent']}")
        try:
            conn = get_snowflake_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

                if not rows:
                    return (
                        f"**Verified Query Executed** ({best['intent']}):\n"
                        f"```sql\n{sql}\n```\n\nQuery returned no results."
                    )

                lines = [f"**Verified Query Executed** ({best['intent']}):\n```sql\n{sql}\n```\n"]
                lines.append(f"Query returned {len(rows)} row(s):\n")
                lines.append("| " + " | ".join(columns) + " |")
                lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
                for row in rows:
                    lines.append("| " + " | ".join(str(v) if v is not None else "NULL" for v in row) + " |")
                return "\n".join(lines)
            finally:
                cursor.close()
        except Exception as e:
            log(f"  Verified query execution failed: {e}")
            # Fall through to return template
            pass

    # If we couldn't auto-execute, return the template
    result = (
        f"**Verified Query Found (MUST USE):**\n"
        f"- Intent: {best['intent']}\n"
        f"- Description: {best['description']}\n"
        f"- SQL:\n```sql\n{sql}\n```\n\n"
        f"**IMPORTANT:** Use the exact tables and columns from this query. "
        f"Only add WHERE filters for specific values. Do NOT use different tables or columns."
    )

    if len(matches) > 1 and matches[1][0] >= matches[0][0] * 0.5:
        alt = matches[1][1]
        result += (
            f"\n\n**Alternative Match:**\n"
            f"- Intent: {alt['intent']}\n"
            f"- SQL:\n```sql\n{alt['sql']}\n```"
        )

    return result


# --- Snowflake Tools ---
@tool
def list_objects(object_type: str = "schema", schema_name: str = "") -> str:
    """List database objects (schemas or tables) in Snowflake.

    Args:
        object_type: Type of object to list - 'schema' or 'table'.
        schema_name: Schema name to list tables from (required when object_type is 'table').

    Returns:
        A formatted list of the requested objects.
    """
    conn = get_snowflake_connection()
    cursor = conn.cursor()
    try:
        if object_type.lower() == "schema":
            cursor.execute(f"SHOW SCHEMAS IN DATABASE {database}")
        elif object_type.lower() == "table":
            if schema_name:
                cursor.execute(f"SHOW TABLES IN SCHEMA {database}.{schema_name}")
            else:
                cursor.execute(f"SHOW TABLES IN DATABASE {database}")
        else:
            return f"Unknown object_type: {object_type}. Use 'schema' or 'table'."

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        if not rows:
            return f"No {object_type}s found."

        # Format as markdown table with key columns
        name_col = next((i for i, c in enumerate(columns) if c.lower() == "name"), 0)
        result_lines = [f"Found {len(rows)} {object_type}(s):\n"]
        for row in rows:
            result_lines.append(f"- {row[name_col]}")
        return "\n".join(result_lines)
    finally:
        cursor.close()


@tool
def describe_object(object_name: str) -> str:
    """Describe the columns of a Snowflake table or view.

    Args:
        object_name: Fully qualified table name (e.g., DATABASE.SCHEMA.TABLE).

    Returns:
        A markdown table describing the columns.
    """
    conn = get_snowflake_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DESCRIBE TABLE {object_name}")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        if not rows:
            return f"No columns found for {object_name}."

        # Format as markdown table
        name_idx = next((i for i, c in enumerate(columns) if c.lower() == "name"), 0)
        type_idx = next((i for i, c in enumerate(columns) if c.lower() == "type"), 1)

        lines = [f"Columns in {object_name}:\n"]
        lines.append("| Column Name | Data Type |")
        lines.append("|-------------|-----------|")
        for row in rows:
            lines.append(f"| {row[name_idx]} | {row[type_idx]} |")
        return "\n".join(lines)
    finally:
        cursor.close()


# --- SQL AST Validation with sqlglot ---
import sqlglot
from sqlglot import exp

# Columns that must never appear in SELECT output (FERPA PII)
_PII_COLUMNS = frozenset({
    "FIRST_NAME", "LAST_NAME", "MIDDLE_NAME", "EMAIL", "EMAIL_ADDRESS",
    "SSN", "SOCIAL_SECURITY_NUMBER", "PHONE", "PHONE_NUMBER", "MOBILE_PHONE",
    "HOME_PHONE", "ADDRESS", "STREET_ADDRESS", "MAILING_ADDRESS",
    "DATE_OF_BIRTH", "DOB", "BIRTH_DATE", "STUDENT_NAME", "FULL_NAME",
    "USERNAME", "LOGIN_ID", "PASSWORD",
})

# Allowed schema prefixes (CDM data model only)
_ALLOWED_SCHEMA_PREFIXES = ("CDM_",)

# Maximum row limit
_MAX_ROW_LIMIT = 1000


def _validate_sql_ast(query: str) -> str | None:
    """Validate SQL via AST parsing. Returns error string or None if valid."""
    try:
        statements = sqlglot.parse(query, dialect="snowflake")
    except sqlglot.errors.ParseError as e:
        return f"SQL parse error: {e}"

    if not statements:
        return "Empty SQL query."

    # Block multiple statements (prevents ; DROP TABLE injection)
    if len(statements) > 1:
        return "ERROR: Multiple SQL statements are not allowed. Only a single SELECT/WITH query is permitted."

    stmt = statements[0]

    # Only allow SELECT and SHOW statements
    if not isinstance(stmt, (exp.Select, exp.Command)):
        return f"ERROR: Only SELECT/WITH/SHOW queries are allowed. Got: {type(stmt).__name__}"

    # For SHOW commands, allow them through (used for schema discovery)
    if isinstance(stmt, exp.Command):
        if str(stmt.this).upper() in ("SHOW", "DESCRIBE", "DESC"):
            return None
        return f"ERROR: Command '{stmt.this}' is not allowed. Only SELECT/WITH/SHOW queries are permitted."

    # Check for dangerous expressions in the AST
    for node in stmt.walk():
        # Block any DML/DDL hidden in subqueries
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop,
                             exp.Create, exp.Alter)):
            return f"ERROR: {type(node).__name__} operations are not allowed."

    # Validate table references — only CDM_* schemas allowed
    for table in stmt.find_all(exp.Table):
        schema_name = table.db  # In Snowflake: database.schema.table — db is the schema
        if schema_name:
            schema_upper = schema_name.upper()
            if not any(schema_upper.startswith(p) for p in _ALLOWED_SCHEMA_PREFIXES):
                # Also allow the database-level references (e.g., INFORMATION_SCHEMA)
                if schema_upper not in ("INFORMATION_SCHEMA",):
                    return f"ERROR: Schema '{schema_name}' is not in the allowed list. Only CDM_* schemas are permitted."

    # Check for PII columns in the top-level SELECT (not in subqueries used for JOINs/aggregation)
    # Only flag if the column appears in the outermost SELECT without a GROUP BY
    select_columns = set()
    for col_expr in stmt.find_all(exp.Column):
        # Only check columns in the outermost select's projections
        parent_select = col_expr.find_ancestor(exp.Select)
        if parent_select is stmt:
            col_name = col_expr.name.upper() if col_expr.name else ""
            select_columns.add(col_name)

    pii_in_select = select_columns & _PII_COLUMNS
    if pii_in_select:
        # Allow PII columns only if they're used in JOINs/WHERE, not in final output
        # Check if there's a GROUP BY (aggregation makes individual PII less risky)
        has_group_by = stmt.find(exp.Group) is not None
        has_agg = any(isinstance(n, (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max))
                      for n in stmt.walk())
        if not (has_group_by or has_agg):
            return (
                f"ERROR: FERPA violation — query selects PII columns ({', '.join(sorted(pii_in_select))}) "
                f"without aggregation. Use GROUP BY or aggregate functions to anonymize data."
            )

    # Enforce LIMIT clause (max 1000 rows)
    limit_node = stmt.find(exp.Limit)
    if limit_node:
        try:
            limit_val = int(limit_node.expression.this)
            if limit_val > _MAX_ROW_LIMIT:
                return f"ERROR: LIMIT {limit_val} exceeds maximum of {_MAX_ROW_LIMIT}. Use LIMIT {_MAX_ROW_LIMIT} or less."
        except (ValueError, AttributeError):
            pass  # Dynamic limit, allow through

    return None  # Valid


@tool
def run_snowflake_query(query: str) -> str:
    """Execute a SQL SELECT query against Snowflake and return results.

    Args:
        query: The SQL SELECT query to execute. Must be a SELECT statement.

    Returns:
        Query results formatted as a markdown table.
    """
    # Quick prefix check for SHOW queries (not parseable by sqlglot as SELECT)
    query_stripped = query.strip()
    query_upper = query_stripped.upper()

    if query_upper.startswith("SHOW") or query_upper.startswith("DESCRIBE") or query_upper.startswith("DESC"):
        # Simple SHOW/DESCRIBE — allow with basic safety check
        if ";" in query_stripped[4:]:
            return "ERROR: Multiple statements are not allowed."
    else:
        # Full AST validation for SELECT/WITH queries
        validation_error = _validate_sql_ast(query_stripped)
        if validation_error:
            return validation_error

    conn = get_snowflake_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        if not rows:
            return f"**SQL Executed:**\n```sql\n{query}\n```\n\nQuery returned no results."

        # Enforce row limit at the result level as a safety net
        if len(rows) > _MAX_ROW_LIMIT:
            rows = rows[:_MAX_ROW_LIMIT]
            truncated_note = f"\n\n*Results truncated to {_MAX_ROW_LIMIT} rows.*"
        else:
            truncated_note = ""

        # Format as markdown table, with the SQL statement included
        lines = [f"**SQL Executed:**\n```sql\n{query}\n```\n"]
        lines.append(f"Query returned {len(rows)} row(s):\n")
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(v) if v is not None else "NULL" for v in row) + " |")
        return "\n".join(lines) + truncated_note
    finally:
        cursor.close()


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
    name="Illuminate SQL Agent",
    description="Generates and executes SQL queries against Snowflake educational data.",
    model=bedrock_model,
    tools=[lookup_verified_query, list_objects, describe_object, run_snowflake_query],
    system_prompt=SQL_SYSTEM_PROMPT,
    callback_handler=None,
)

executor = StrandsA2AExecutor(strands_agent)
log("DONE: Agent initialized")

# Build the Starlette app with /ping and A2A routes
_inner_app = build_a2a_app(executor)
log("Inner app built (Starlette with /ping + A2A routes)")


# --- Verified Query Short-Circuit Middleware ---
# Intercepts A2A requests BEFORE the LLM. If the user's question matches a
# verified query, execute it directly and return the result — the LLM never
# sees the request, guaranteeing 100% deterministic output for known patterns.

_STRONG_MATCH_THRESHOLD = 1.5  # Minimum score to short-circuit (lowered for better coverage)


def _try_verified_query_shortcircuit(message_text: str) -> str | None:
    """Try to answer via verified query. Returns formatted result or None."""
    if not _verified_queries:
        return None

    # The orchestrator often wraps the question with schema guidance context.
    # Try matching the full message first, then extract shorter question fragments.
    candidates = [message_text.lower()]

    # Extract every line that contains a question mark
    for line in message_text.split("\n"):
        line = line.strip()
        if len(line) > 10 and len(line) < 300 and "?" in line:
            candidates.append(line.lower())

    # Try first line (often the raw question or the most relevant part)
    first_line = message_text.strip().split("\n")[0].strip()
    if first_line and len(first_line) < 300:
        candidates.append(first_line.lower())

    # Extract sentences containing GPA, enrollment, student, grade, etc.
    for sentence in _re.split(r'[.\n]', message_text):
        sentence = sentence.strip()
        if len(sentence) > 5 and any(kw in sentence.lower() for kw in
                                      ["gpa", "enrollment", "student count", "grade distribution",
                                       "how many", "average", "completion rate"]):
            candidates.append(sentence.lower())

    best_score = 0.0
    best = None
    for candidate in candidates:
        for entry in _verified_queries:
            score = _score_query_match(candidate, entry)
            if score > best_score:
                best_score = score
                best = entry

    if not best or best_score < _STRONG_MATCH_THRESHOLD:
        return None  # Not confident enough to bypass LLM

    sql = best["sql"]

    # Auto-substitute term name — search the full message for term references
    term_name = _extract_term_filter(message_text)
    if "<TERM_NAME>" in sql and term_name:
        sql = sql.replace("<TERM_NAME>", term_name)
    elif "<TERM_NAME>" in sql:
        return None  # Need a term name but can't extract one

    # Add term filter for queries that don't have a placeholder but user specified a term
    if term_name and "TERM" in sql.upper() and term_name.lower() not in sql.lower():
        if "WHERE" in sql.upper():
            sql = _re.sub(
                r'(WHERE\s)',
                f"\\1t.NAME ILIKE '%{term_name}%' AND ",
                sql, count=1, flags=_re.IGNORECASE,
            )
        elif "GROUP BY" in sql.upper():
            sql = _re.sub(
                r'(GROUP BY)',
                f"WHERE t.NAME ILIKE '%{term_name}%' \\1",
                sql, count=1, flags=_re.IGNORECASE,
            )

    if "<" in sql:
        return None  # Still has unresolved placeholders

    # Execute the verified query
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            if not rows:
                return (
                    f"**Verified Query:** {best['intent']}\n\n"
                    f"**SQL Executed:**\n```sql\n{sql}\n```\n\n"
                    f"Query returned no results."
                )

            lines = [
                f"**Verified Query:** {best['intent']}\n\n"
                f"**SQL Executed:**\n```sql\n{sql}\n```\n"
            ]
            lines.append(f"Query returned {len(rows)} row(s):\n")
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(v) if v is not None else "NULL" for v in row) + " |")
            return "\n".join(lines)
        finally:
            cursor.close()
    except Exception as e:
        log(f"  Verified query short-circuit failed: {e}")
        return None  # Fall through to LLM


class VerifiedQueryMiddleware:
    """ASGI middleware that short-circuits verified queries before the LLM."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)

        # Check if this is a /ping (health check) — pass through
        path = scope.get("path", "")
        if path == "/ping":
            return await self.app(scope, receive, send)

        # Read the request body
        body_parts = []
        body_complete = False

        async def receive_wrapper():
            nonlocal body_complete
            message = await receive()
            if message.get("type") == "http.request":
                body_parts.append(message.get("body", b""))
                if not message.get("more_body", False):
                    body_complete = True
            return message

        raw_body = b""
        while not body_complete:
            msg = await receive_wrapper()
            if msg.get("type") == "http.disconnect":
                return

        raw_body = b"".join(body_parts)

        # Try to extract the user message and check against verified queries
        shortcircuit_result = None
        request_id = None
        try:
            payload = json.loads(raw_body)
            request_id = payload.get("id")
            params = payload.get("params", {})
            if isinstance(params, dict):
                message = params.get("message", {})
                if isinstance(message, dict):
                    for part in message.get("parts", []):
                        if part.get("kind") == "text" and part.get("text"):
                            text = part["text"]
                            shortcircuit_result = _try_verified_query_shortcircuit(text)
                            if shortcircuit_result:
                                log(f"  SHORTCIRCUIT: verified query matched for: {text[:80]}...")
                            break
        except (json.JSONDecodeError, AttributeError):
            pass

        if shortcircuit_result:
            # Return the verified query result directly as an A2A response
            response_body = json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "artifacts": [{
                        "parts": [{"kind": "text", "text": shortcircuit_result}],
                    }],
                },
            }).encode()

            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })
            return

        # No match — replay body and pass through to LLM agent
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


app = VerifiedQueryMiddleware(_inner_app)
log("App wrapped with verified query short-circuit middleware")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9000"))
    log(f"Starting uvicorn on 0.0.0.0:{port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port)
