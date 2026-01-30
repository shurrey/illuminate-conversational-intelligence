"""
Snowflake MCP Server integration for Strands Agents.

Strands Agents natively handles MCP protocol communication. This module
manages the Snowflake MCP server subprocess lifecycle and provides
mock tools for development without a Snowflake connection.

Architecture:
    Strands Agent → MCPClient → snowflake-labs-mcp (subprocess) → Snowflake

The MCP server runs as a subprocess via `uvx`, using its own Python
environment, which avoids Python version compatibility issues with
snowflake-connector-python.
"""
import os
import json
import logging
from typing import Optional

logger = logging.getLogger("SNOWFLAKE")


# ============================================================
# Mock data for development mode
# ============================================================

MOCK_DATA = {
    "CDM_LMS": {
        "COURSE": [
            {"COURSE_ID": "C001", "COURSE_NAME": "Introduction to Computer Science", "TERM": "Fall 2024", "DEPARTMENT": "Computer Science", "INSTRUCTOR_NAME": "Dr. Smith", "ENROLLMENT_COUNT": 150},
            {"COURSE_ID": "C002", "COURSE_NAME": "Data Structures", "TERM": "Fall 2024", "DEPARTMENT": "Computer Science", "INSTRUCTOR_NAME": "Dr. Johnson", "ENROLLMENT_COUNT": 120},
            {"COURSE_ID": "C003", "COURSE_NAME": "Calculus I", "TERM": "Fall 2024", "DEPARTMENT": "Mathematics", "INSTRUCTOR_NAME": "Dr. Williams", "ENROLLMENT_COUNT": 200},
            {"COURSE_ID": "C004", "COURSE_NAME": "English Composition", "TERM": "Fall 2024", "DEPARTMENT": "English", "INSTRUCTOR_NAME": "Prof. Brown", "ENROLLMENT_COUNT": 180},
            {"COURSE_ID": "C005", "COURSE_NAME": "Psychology 101", "TERM": "Fall 2024", "DEPARTMENT": "Psychology", "INSTRUCTOR_NAME": "Dr. Davis", "ENROLLMENT_COUNT": 220},
        ],
        "GRADE": [
            {"GRADE_ID": "G001", "COURSE_ID": "C001", "PERSON_ID": "P001", "GRADE_VALUE": "A", "GRADE_POINTS": 4.0},
            {"GRADE_ID": "G002", "COURSE_ID": "C001", "PERSON_ID": "P002", "GRADE_VALUE": "B+", "GRADE_POINTS": 3.3},
            {"GRADE_ID": "G003", "COURSE_ID": "C002", "PERSON_ID": "P001", "GRADE_VALUE": "A-", "GRADE_POINTS": 3.7},
            {"GRADE_ID": "G004", "COURSE_ID": "C003", "PERSON_ID": "P003", "GRADE_VALUE": "B", "GRADE_POINTS": 3.0},
            {"GRADE_ID": "G005", "COURSE_ID": "C004", "PERSON_ID": "P002", "GRADE_VALUE": "A", "GRADE_POINTS": 4.0},
            {"GRADE_ID": "G006", "COURSE_ID": "C005", "PERSON_ID": "P004", "GRADE_VALUE": "B-", "GRADE_POINTS": 2.7},
            {"GRADE_ID": "G007", "COURSE_ID": "C001", "PERSON_ID": "P005", "GRADE_VALUE": "A-", "GRADE_POINTS": 3.7},
            {"GRADE_ID": "G008", "COURSE_ID": "C002", "PERSON_ID": "P006", "GRADE_VALUE": "C+", "GRADE_POINTS": 2.3},
            {"GRADE_ID": "G009", "COURSE_ID": "C003", "PERSON_ID": "P007", "GRADE_VALUE": "A", "GRADE_POINTS": 4.0},
            {"GRADE_ID": "G010", "COURSE_ID": "C004", "PERSON_ID": "P008", "GRADE_VALUE": "B+", "GRADE_POINTS": 3.3},
        ],
        "PERSON_COURSE": [
            {"PERSON_ID": "P001", "COURSE_ID": "C001", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P001", "COURSE_ID": "C002", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P002", "COURSE_ID": "C001", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P002", "COURSE_ID": "C004", "ROLE": "Student", "ENROLLMENT_STATUS": "Completed"},
            {"PERSON_ID": "P003", "COURSE_ID": "C003", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P004", "COURSE_ID": "C005", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P005", "COURSE_ID": "C001", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P006", "COURSE_ID": "C002", "ROLE": "Student", "ENROLLMENT_STATUS": "Dropped"},
            {"PERSON_ID": "P007", "COURSE_ID": "C003", "ROLE": "Student", "ENROLLMENT_STATUS": "Active"},
            {"PERSON_ID": "P008", "COURSE_ID": "C004", "ROLE": "Student", "ENROLLMENT_STATUS": "Completed"},
        ],
        "ASSIGNMENT": [
            {"ASSIGNMENT_ID": "A001", "COURSE_ID": "C001", "TITLE": "Homework 1", "DUE_DATE": "2024-09-15", "SUBMISSIONS": 145, "AVG_SCORE": 85.5},
            {"ASSIGNMENT_ID": "A002", "COURSE_ID": "C001", "TITLE": "Midterm Exam", "DUE_DATE": "2024-10-20", "SUBMISSIONS": 148, "AVG_SCORE": 78.2},
            {"ASSIGNMENT_ID": "A003", "COURSE_ID": "C002", "TITLE": "Lab 1", "DUE_DATE": "2024-09-10", "SUBMISSIONS": 118, "AVG_SCORE": 92.0},
            {"ASSIGNMENT_ID": "A004", "COURSE_ID": "C003", "TITLE": "Problem Set 1", "DUE_DATE": "2024-09-12", "SUBMISSIONS": 195, "AVG_SCORE": 72.8},
            {"ASSIGNMENT_ID": "A005", "COURSE_ID": "C004", "TITLE": "Essay 1", "DUE_DATE": "2024-09-20", "SUBMISSIONS": 176, "AVG_SCORE": 81.0},
        ],
    },
}

# Table schemas for mock describe_table (CDM_LMS only)
TABLE_SCHEMAS = {
    "CDM_LMS.COURSE": [
        {"COLUMN_NAME": "COURSE_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Unique course identifier"},
        {"COLUMN_NAME": "COURSE_NAME", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Course title"},
        {"COLUMN_NAME": "TERM", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Academic term"},
        {"COLUMN_NAME": "DEPARTMENT", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Academic department"},
        {"COLUMN_NAME": "INSTRUCTOR_NAME", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Primary instructor"},
        {"COLUMN_NAME": "ENROLLMENT_COUNT", "DATA_TYPE": "INTEGER", "IS_NULLABLE": "YES", "COMMENT": "Number of enrolled students"},
    ],
    "CDM_LMS.GRADE": [
        {"COLUMN_NAME": "GRADE_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Unique grade record ID"},
        {"COLUMN_NAME": "COURSE_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Associated course"},
        {"COLUMN_NAME": "PERSON_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Student identifier"},
        {"COLUMN_NAME": "GRADE_VALUE", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Letter grade"},
        {"COLUMN_NAME": "GRADE_POINTS", "DATA_TYPE": "FLOAT", "IS_NULLABLE": "YES", "COMMENT": "Grade points (4.0 scale)"},
    ],
    "CDM_LMS.PERSON_COURSE": [
        {"COLUMN_NAME": "PERSON_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Student identifier"},
        {"COLUMN_NAME": "COURSE_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Course identifier"},
        {"COLUMN_NAME": "ROLE", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Role (Student, Instructor, TA)"},
        {"COLUMN_NAME": "ENROLLMENT_STATUS", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Status (Active, Dropped, Completed)"},
    ],
    "CDM_LMS.ASSIGNMENT": [
        {"COLUMN_NAME": "ASSIGNMENT_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Unique assignment ID"},
        {"COLUMN_NAME": "COURSE_ID", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "NO", "COMMENT": "Associated course"},
        {"COLUMN_NAME": "TITLE", "DATA_TYPE": "VARCHAR", "IS_NULLABLE": "YES", "COMMENT": "Assignment title"},
        {"COLUMN_NAME": "DUE_DATE", "DATA_TYPE": "DATE", "IS_NULLABLE": "YES", "COMMENT": "Due date"},
        {"COLUMN_NAME": "SUBMISSIONS", "DATA_TYPE": "INTEGER", "IS_NULLABLE": "YES", "COMMENT": "Number of submissions"},
        {"COLUMN_NAME": "AVG_SCORE", "DATA_TYPE": "FLOAT", "IS_NULLABLE": "YES", "COMMENT": "Average score"},
    ],
}


def is_mock_mode() -> bool:
    """Check if mock mode is enabled."""
    return os.environ.get("ILLUMINATE_MOCK_MODE", "true").lower() == "true"


# ============================================================
# Mock tools - match the Snowflake MCP server tool interface
# ============================================================

def get_mock_tools() -> list:
    """
    Get mock tools that simulate the Snowflake MCP server.

    These tools have the same names and signatures as the real MCP server
    tools, so agents work identically in mock and real modes.
    """
    from strands import tool

    @tool
    def read_query(query: str) -> str:
        """Execute a read-only SQL query against the Illuminate data warehouse.

        Use this tool to run SELECT queries against Snowflake. Only SELECT
        statements are permitted. Results are returned as JSON.

        Args:
            query: The SQL SELECT query to execute
        """
        query_lower = query.lower().strip()

        # Parse table name from query
        table_name = None
        schema_name = None
        if "from" in query_lower:
            parts = query_lower.split("from")
            if len(parts) > 1:
                table_part = parts[1].strip().split()[0]
                # Handle schema.table format
                if "." in table_part:
                    schema_table = table_part.split(".")
                    schema_name = schema_table[0].upper()
                    table_name = schema_table[-1].upper()
                else:
                    table_name = table_part.upper()

        # Find matching data
        results = []
        for schema, tables in MOCK_DATA.items():
            if schema_name and schema != schema_name:
                continue
            if table_name and table_name in tables:
                results = list(tables[table_name])
                break

        # Handle JOINs - if query has JOIN, merge data from joined tables
        if "join" in query_lower and results:
            # Simple handling - just return the primary table data
            pass

        # Handle WHERE clauses (basic filtering)
        if "where" in query_lower and results:
            where_part = query_lower.split("where")[1].split("group")[0].split("order")[0].split("limit")[0]
            # Basic equality filter
            if "=" in where_part and "!=" not in where_part and "<=" not in where_part and ">=" not in where_part:
                for condition in where_part.split("and"):
                    condition = condition.strip()
                    if "=" in condition and "like" not in condition.lower():
                        parts = condition.split("=")
                        if len(parts) == 2:
                            col = parts[0].strip().split(".")[-1].upper()
                            val = parts[1].strip().strip("'\"")
                            results = [r for r in results if str(r.get(col, "")).lower() == val.lower()]

        # Handle aggregation queries
        if any(agg in query_lower for agg in ["avg(", "count(", "sum(", "min(", "max("]):
            if "group by" in query_lower:
                # Simple group-by aggregation
                group_col = query_lower.split("group by")[1].strip().split(",")[0].strip().split()[0]
                group_col = group_col.split(".")[-1].upper()
                groups: dict[str, list] = {}
                for row in results:
                    key = str(row.get(group_col, "Unknown"))
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(row)

                agg_results = []
                for key, rows in groups.items():
                    agg_row = {"category": key, "count": len(rows)}
                    # Calculate AVG for numeric fields
                    for col in rows[0]:
                        if isinstance(rows[0][col], (int, float)):
                            values = [r[col] for r in rows if isinstance(r.get(col), (int, float))]
                            if values:
                                agg_row[f"avg_{col.lower()}"] = round(sum(values) / len(values), 2)
                    agg_results.append(agg_row)
                results = agg_results
            else:
                # Global aggregation
                if results:
                    agg_row = {"count": len(results)}
                    for col in results[0]:
                        if isinstance(results[0][col], (int, float)):
                            values = [r[col] for r in results if isinstance(r.get(col), (int, float))]
                            if values:
                                agg_row[f"avg_{col.lower()}"] = round(sum(values) / len(values), 2)
                                agg_row[f"min_{col.lower()}"] = min(values)
                                agg_row[f"max_{col.lower()}"] = max(values)
                    results = [agg_row]

        # Handle LIMIT
        if "limit" in query_lower:
            limit_parts = query_lower.split("limit")
            if len(limit_parts) > 1:
                try:
                    limit = int(limit_parts[-1].strip().split()[0])
                    results = results[:limit]
                except (ValueError, IndexError):
                    pass

        return json.dumps({
            "columns": list(results[0].keys()) if results else [],
            "data": results,
            "row_count": len(results),
            "status": "success"
        }, indent=2)

    @tool
    def list_tables(schema_name: str = "") -> str:
        """List available tables in the Illuminate data warehouse.

        Args:
            schema_name: Schema to list tables from (e.g., CDM_LMS, CDM_SIS, CDM_TLM).
                        If empty, lists tables from all schemas.
        """
        tables = []
        schema_upper = schema_name.upper() if schema_name else ""

        for schema, schema_tables in MOCK_DATA.items():
            if schema_upper and schema != schema_upper:
                continue
            for table_name in schema_tables:
                row_count = len(schema_tables[table_name])
                tables.append({
                    "schema": schema,
                    "table_name": table_name,
                    "full_name": f"{schema}.{table_name}",
                    "row_count": row_count
                })

        return json.dumps(tables, indent=2)

    @tool
    def describe_table(table_name: str) -> str:
        """Get column information for a specific table.

        Args:
            table_name: Full table name (e.g., CDM_LMS.COURSE) or just table name
        """
        # Normalize the table name
        table_upper = table_name.upper()
        if "." not in table_upper:
            # Search all schemas
            for full_name, schema in TABLE_SCHEMAS.items():
                if full_name.endswith(f".{table_upper}"):
                    return json.dumps({
                        "table": full_name,
                        "columns": schema
                    }, indent=2)
        elif table_upper in TABLE_SCHEMAS:
            return json.dumps({
                "table": table_upper,
                "columns": TABLE_SCHEMAS[table_upper]
            }, indent=2)

        return json.dumps({"error": f"Table '{table_name}' not found"})

    return [read_query, list_tables, describe_table]


# ============================================================
# Real Snowflake MCP Server connection
# ============================================================

def create_snowflake_mcp_client(
    allowed_tools: Optional[list[str]] = None,
    prefix: Optional[str] = None
):
    """
    Create a Strands MCPClient for the Snowflake MCP server.

    The snowflake-labs-mcp server runs as a subprocess via `uvx` with its
    own Python environment. Strands handles the MCP protocol communication.

    Args:
        allowed_tools: Tool names to expose (default: read_query, list_tables, describe_table)
        prefix: Optional prefix for tool names to avoid collisions

    Returns:
        MCPClient instance (use with `with` block or pass to Agent)
    """
    from strands.tools.mcp import MCPClient
    from mcp import stdio_client, StdioServerParameters

    # Build environment for the MCP server subprocess
    env = dict(os.environ)
    env.update({
        "SNOWFLAKE_ACCOUNT": os.environ.get("SNOWFLAKE_ACCOUNT", ""),
        "SNOWFLAKE_USER": os.environ.get("SNOWFLAKE_USER", ""),
        "SNOWFLAKE_PASSWORD": os.environ.get("SNOWFLAKE_PASSWORD", ""),
        "SNOWFLAKE_WAREHOUSE": os.environ.get("SNOWFLAKE_WAREHOUSE", "BLACKBOARD_DATA_WH"),
        "SNOWFLAKE_DATABASE": os.environ.get("SNOWFLAKE_DATABASE", ""),
        "SNOWFLAKE_ROLE": os.environ.get("SNOWFLAKE_ROLE", "BBDATA_USER_ROLE"),
        # Force password auth instead of external browser auth
        "SNOWFLAKE_AUTHENTICATOR": "snowflake",
    })

    # Optional: private key auth
    for key in ["SNOWFLAKE_PRIVATE_KEY", "SNOWFLAKE_PRIVATE_KEY_FILE"]:
        val = os.environ.get(key)
        if val:
            env[key] = val

    # Service config path - use absolute path from this file's location
    this_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.normpath(os.path.join(this_dir, "..", "..", "config", "illuminate-mcp-server.yaml"))

    logger.info(f"Snowflake MCP config path: {config_path}")
    logger.info(f"Config exists: {os.path.exists(config_path)}")

    # Use Python 3.13 explicitly - snowflake-connector-python doesn't support Python 3.14
    args = ["--python", "3.13", "snowflake-labs-mcp"]

    # Add config file
    if os.path.exists(config_path):
        args.extend(["--service-config-file", config_path])
    else:
        logger.error(f"Config file not found at: {config_path}")

    # Add explicit connection parameters for headless auth
    # This ensures password auth instead of external browser auth
    account = os.environ.get("SNOWFLAKE_ACCOUNT", "")
    user = os.environ.get("SNOWFLAKE_USER", "")
    password = os.environ.get("SNOWFLAKE_PASSWORD", "")
    database = os.environ.get("SNOWFLAKE_DATABASE", "")
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "BLACKBOARD_DATA_WH")
    role = os.environ.get("SNOWFLAKE_ROLE", "BBDATA_USER_ROLE")

    # Log database being used (passed via env var, not CLI flag)
    if database:
        logger.info(f"Using Snowflake database: {database} (via env var)")

    if account and user:
        args.extend(["--account", account, "--user", user])
        if password:
            args.extend(["--password", password, "--authenticator", "snowflake"])
        # Note: --database is not a valid CLI flag for snowflake-labs-mcp
        # Database is passed via SNOWFLAKE_DATABASE env var instead
        if warehouse:
            args.extend(["--warehouse", warehouse])
        if role:
            args.extend(["--role", role])

    # Log args without exposing password
    safe_args = []
    skip_next = False
    for a in args:
        if skip_next:
            safe_args.append("***")
            skip_next = False
        elif a == "--password":
            safe_args.append(a)
            skip_next = True
        else:
            safe_args.append(a)
    logger.info(f"MCP server args: {safe_args}")

    tool_filters = None
    if allowed_tools:
        tool_filters = {"allowed": allowed_tools}

    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="uvx",
            args=args,
            env=env
        )),
        tool_filters=tool_filters,
        prefix=prefix
    )


# ============================================================
# Lifecycle Manager
# ============================================================

class SnowflakeMCPManager:
    """
    Manages the lifecycle of the Snowflake MCP server connection.

    In mock mode, provides mock tools that simulate the MCP server.
    In real mode, starts the snowflake-labs-mcp subprocess and connects
    via Strands MCPClient.

    Use as a context manager or call start()/stop() for long-running servers.
    """

    def __init__(self):
        self._client = None
        self._tools = None
        self._mock_mode = is_mock_mode()

    def start(self):
        """Start the MCP server connection (or load mock tools)."""
        if self._mock_mode:
            self._tools = get_mock_tools()
            logger.info("Snowflake MCP: Using mock tools (ILLUMINATE_MOCK_MODE=true)")
        else:
            logger.info("Snowflake MCP: Connecting to Snowflake MCP server...")
            # Don't filter tools initially - let's see what the server provides
            self._client = create_snowflake_mcp_client(
                allowed_tools=None  # Get all tools first, filter later if needed
            )
            self._client.__enter__()
            self._tools = self._client.list_tools_sync()
            # Get tool names - MCPAgentTool uses tool_name property
            tool_names = [t.tool_name for t in self._tools]
            logger.info(f"Snowflake MCP: Connected, {len(tool_names)} tools available: {tool_names}")

            # Discover and cache schema at startup so agents have accurate column names
            self._discover_and_cache_schema()

    def _discover_and_cache_schema(self):
        """Discover database schema using a Strands Agent with MCP tools.

        Discovers schemas one at a time to avoid token limits.
        Uses a single agent instance for all schemas to avoid event loop issues.
        """
        try:
            from agents.shared.schema_cache import get_schema_cache, SchemaInfo, TableInfo, ColumnInfo
            from strands import Agent
            from strands.models.anthropic import AnthropicModel

            cache = get_schema_cache()

            if cache.is_discovered:
                logger.info("Schema already cached, skipping discovery")
                return

            database = os.environ.get("SNOWFLAKE_DATABASE", "")
            if not database:
                logger.warning("SNOWFLAKE_DATABASE not set, skipping schema discovery")
                return

            logger.info("Starting schema discovery with Strands Agent...")
            cache._database = database

            # Create a single discovery agent to avoid event loop cleanup issues
            discovery_agent = Agent(
                model=AnthropicModel(
                    model_id="claude-sonnet-4-20250514",
                    max_tokens=8192  # Higher limit for large schemas
                ),
                tools=self._tools,
                system_prompt="""You are a schema discovery agent. Your job is to discover tables and columns.

IMPORTANT: Be concise. Only output table names and column names, nothing else.

When done, output JSON in this EXACT format (no extra text):
```json
{"tables": {"TABLE_NAME": ["COL1", "COL2", ...]}}
```

If a schema has no tables, output: {"tables": {}}"""
            )

            # Discover each schema separately to avoid token limits
            schemas_to_discover = ["CDM_LMS"]

            for schema_name in schemas_to_discover:
                try:
                    schema_info = self._discover_single_schema(database, schema_name, discovery_agent)
                    if schema_info:
                        cache._schemas[schema_name] = schema_info
                        logger.info(f"Cached {len(schema_info.tables)} tables from {schema_name}")
                    else:
                        logger.warning(f"No tables found in {schema_name}")
                except Exception as e:
                    logger.error(f"Failed to discover schema {schema_name}: {e}")

            cache._discovered = True
            logger.info(f"Schema discovery complete: {len(cache._schemas)} schemas cached")

        except Exception as e:
            logger.error(f"Schema discovery failed: {e}", exc_info=True)

    def _discover_single_schema(self, database: str, schema_name: str, discovery_agent):
        """Discover tables and columns for a single schema."""
        from agents.shared.schema_cache import SchemaInfo, TableInfo, ColumnInfo

        logger.info(f"Discovering schema: {schema_name}")

        # Run discovery for this schema using the shared agent
        result = discovery_agent(
            f"List all tables in database={database}, schema={schema_name} using list_objects. "
            f"Then for EACH table, get its columns using describe_object. "
            f"Output only table names and column names as JSON."
        )
        result_text = str(result)

        # Parse the result
        schema_data = self._parse_discovery_result(result_text)

        if schema_data and "tables" in schema_data:
            si = SchemaInfo(name=schema_name, database=database)
            for table_name, columns in schema_data["tables"].items():
                ti = TableInfo(name=table_name, schema=schema_name, database=database)
                for col_name in columns:
                    ti.columns.append(ColumnInfo(name=col_name, data_type="VARCHAR"))
                si.tables[table_name] = ti
            return si

        return None

    def _parse_discovery_result(self, result_text: str) -> dict:
        """Parse JSON schema data from discovery agent result."""
        import json
        import re

        # Try to find JSON block in the result
        json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON from code block: {e}")

        # Try to find raw JSON object with "tables" key
        json_match = re.search(r'\{[^{}]*"tables"[^{}]*\{[^}]*\}[^}]*\}', result_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse raw JSON: {e}")

        # If JSON parsing failed, try to extract table/column info from tool results
        # Look for patterns like "Table: TABLE_NAME" and "Columns: ..."
        tables = {}
        current_table = None

        for line in result_text.split('\n'):
            # Look for table names from list_objects results
            table_match = re.search(r'(?:name|table)["\s:]+([A-Z_]+)', line, re.IGNORECASE)
            if table_match:
                table_name = table_match.group(1).upper()
                if table_name not in ['TABLE', 'NAME', 'OBJECT', 'TYPE']:
                    current_table = table_name
                    if current_table not in tables:
                        tables[current_table] = []

            # Look for column names from describe_object results
            col_match = re.search(r'(?:column|field)["\s:]+([A-Z_]+)', line, re.IGNORECASE)
            if col_match and current_table:
                col_name = col_match.group(1).upper()
                if col_name not in ['COLUMN', 'NAME', 'FIELD']:
                    tables[current_table].append(col_name)

        if tables:
            return {"tables": tables}

        return {}

    def stop(self):
        """Stop the MCP server connection."""
        if self._client:
            try:
                self._client.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error stopping MCP client: {e}")
            self._client = None
        self._tools = None
        logger.info("Snowflake MCP: Disconnected")

    @property
    def tools(self):
        """Get the available Snowflake tools. Starts connection if needed."""
        if self._tools is None:
            self.start()
        return self._tools

    @property
    def is_mock(self) -> bool:
        """Whether running in mock mode."""
        return self._mock_mode

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# Singleton instance
_mcp_manager: Optional[SnowflakeMCPManager] = None


def get_mcp_manager() -> SnowflakeMCPManager:
    """Get or create the singleton MCP manager."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = SnowflakeMCPManager()
    return _mcp_manager
