"""
SQL Agent - Self-contained A2A server for AgentCore deployment.

Generates and executes SQL queries against Snowflake using direct
snowflake-connector-python. Zero `from agents.*` imports.
"""
import json
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

    log("Loading Snowflake credentials ...")
    load_snowflake_credentials()

    log("Importing dependencies ...")
    from strands import Agent, tool
    from strands.models import BedrockModel
    from strands.multiagent.a2a import A2AServer

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
- **list_objects**: Discover available schemas and tables
- **describe_object**: Get column information for a specific table
- **run_snowflake_query**: Execute SQL SELECT queries

## Query Guidelines
1. ALWAYS use fully qualified table names: {database}.CDM_LMS.TABLE_NAME
2. Use the EXACT column names from describe_object results
3. Use LIMIT to avoid returning too many rows (default LIMIT 100)
4. For aggregations, include meaningful GROUP BY clauses
5. Use JOINs when queries span multiple tables

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

    @tool
    def run_snowflake_query(query: str) -> str:
        """Execute a SQL SELECT query against Snowflake and return results.

        Args:
            query: The SQL SELECT query to execute. Must be a SELECT statement.

        Returns:
            Query results formatted as a markdown table.
        """
        # Safety check
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH") and not query_upper.startswith("SHOW"):
            return "ERROR: Only SELECT, WITH, and SHOW queries are allowed."

        conn = get_snowflake_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            if not rows:
                return "Query returned no results."

            # Format as markdown table
            lines = [f"Query returned {len(rows)} row(s):\n"]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(v) if v is not None else "NULL" for v in row) + " |")
            return "\n".join(lines)
        finally:
            cursor.close()

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
        name="Illuminate SQL Agent",
        description="Generates and executes SQL queries against Snowflake educational data.",
        model=bedrock_model,
        tools=[list_objects, describe_object, run_snowflake_query],
        system_prompt=SQL_SYSTEM_PROMPT,
        callback_handler=None,
    )

    # --- Wrap in A2AServer ---
    log("Creating A2AServer ...")
    runtime_url = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")
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
                "result": {"text": f"SQL Agent init failed: {startup_error}"},
                "id": "error",
            },
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
