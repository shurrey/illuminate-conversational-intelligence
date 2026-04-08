"""
Snowflake client for the Lambda proxy.

Provides a lazy-initialized, reusable Snowflake connection for direct
data queries (e.g., table previews). Credentials are loaded from AWS
Secrets Manager on first use.

Imported lazily by lambda_handler.py only when Snowflake endpoints are
hit, so dictionary proxy endpoints don't pay the cold start cost.
"""

import json
import logging
import os

import boto3

logger = logging.getLogger("API-PROXY")

_sf_connection = None
_sf_credentials: dict | None = None


def _load_credentials() -> dict:
    """Load Snowflake credentials from Secrets Manager (cached)."""
    global _sf_credentials
    if _sf_credentials:
        return _sf_credentials

    secret_name = os.environ.get("SNOWFLAKE_SECRET_NAME", "illuminate/dev/snowflake")
    region = os.environ.get("AWS_REGION", "us-east-1")

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    _sf_credentials = json.loads(response["SecretString"])
    logger.info(f"Loaded Snowflake credentials from {secret_name}")
    return _sf_credentials


def get_connection():
    """Get or create a Snowflake connection (lazy, reused across requests)."""
    global _sf_connection
    if _sf_connection is None or _sf_connection.is_closed():
        import snowflake.connector

        creds = _load_credentials()
        _sf_connection = snowflake.connector.connect(
            account=creds.get("account", ""),
            user=creds.get("user", creds.get("username", "")),
            password=creds.get("password", ""),
            database=creds.get("database", ""),
            warehouse=creds.get("warehouse", ""),
            role=creds.get("role", ""),
            network_timeout=30,
            login_timeout=30,
        )
        logger.info("Snowflake connection established")
    return _sf_connection


def query_preview(schema: str, table: str, limit: int = 20) -> dict:
    """Execute SELECT * FROM schema.table LIMIT n and return columns + rows.

    The database is set on the connection from Secrets Manager credentials,
    so only schema and table are needed.

    Returns:
        {"columns": ["COL1", ...], "rows": [{"COL1": val, ...}, ...]}
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Identifiers are double-quoted per Snowflake convention.
        # Callers must validate schema/table before calling this function.
        cursor.execute(f'SELECT * FROM "{schema}"."{table}" LIMIT {limit}')
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return {"columns": columns, "rows": rows}
    finally:
        cursor.close()


def query_sql(sql: str) -> dict:
    """Execute a read-only SQL statement and return columns + rows.

    Only SELECT and WITH statements are allowed.

    Returns:
        {"columns": ["COL1", ...], "rows": [{"COL1": val, ...}, ...]}

    Raises:
        ValueError: If the SQL is not a SELECT/WITH statement.
        Exception: On Snowflake execution errors (caller should catch).
    """
    normalized = sql.strip().upper()
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        raise ValueError("Only SELECT and WITH queries are allowed")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return {"columns": columns, "rows": rows}
    finally:
        cursor.close()
