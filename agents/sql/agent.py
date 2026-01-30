"""
SQL Agent - Generates and executes SQL queries against Snowflake.

This agent uses the Snowflake MCP server tools to:
1. Understand natural language questions
2. Generate appropriate SQL queries
3. Execute queries and return structured results

Unlike the old Learning Agent, the SQL Agent focuses ONLY on data retrieval.
It does not interpret or analyze results - that's the Analyst's job.

Model: Claude Sonnet 4 (fast SQL generation)
Data: CDM_LMS schema (courses, grades, enrollments, assignments)
"""
import os
import asyncio
import logging
from typing import Any, Optional

from strands import Agent

from agents.shared.models import SQLResult

logger = logging.getLogger("SQL")


def _get_system_prompt() -> str:
    """Build system prompt with cached schema information."""
    database = os.environ.get("SNOWFLAKE_DATABASE", "YOUR_DATABASE")

    # Try to get cached schema
    schema_info = ""
    try:
        from agents.shared.schema_cache import get_schema_cache
        cache = get_schema_cache()
        if cache.is_discovered:
            schema_info = cache.get_schema_description("CDM_LMS")
    except Exception:
        pass

    # If no cached schema, provide fallback instructions
    if not schema_info:
        schema_info = f"""## Available Tables in {database}.CDM_LMS
Schema not yet discovered. Use describe_object to get column information before querying.

Common tables: COURSE, GRADE, PERSON_COURSE, ASSIGNMENT, TERM"""

    return f"""You are the SQL Agent for an educational data analytics system.
Your ONLY job is to generate and execute SQL queries. You do NOT analyze or interpret results.

## Your Role
1. Understand what data the user needs
2. Generate accurate SQL queries
3. Execute queries using the run_snowflake_query tool
4. Return the raw data

## IMPORTANT: Database Configuration
The Snowflake database is: {database}
You MUST use fully qualified table names: {database}.CDM_LMS.TABLE_NAME

## Available Tools
- **list_objects**: Discover available schemas and tables
- **describe_object**: Get column information for a specific table
- **run_snowflake_query**: Execute SQL SELECT queries

{schema_info}

## Query Guidelines
1. ALWAYS use fully qualified table names: {database}.CDM_LMS.TABLE_NAME
2. Use the EXACT column names shown above
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


def _get_strands_model():
    """Get the appropriate Strands model (Sonnet for fast SQL generation)."""
    use_bedrock = os.environ.get("USE_BEDROCK", "false").lower() == "true"

    if use_bedrock:
        from strands.models.bedrock import BedrockModel
        return BedrockModel(
            model_id=os.environ.get(
                "BEDROCK_MODEL_ORCHESTRATOR",  # Sonnet tier
                "anthropic.claude-sonnet-4-20250514-v1:0"
            ),
            max_tokens=4096
        )
    else:
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(
            model_id=os.environ.get(
                "MODEL_ORCHESTRATOR",  # Sonnet tier
                "claude-sonnet-4-20250514"
            ),
            max_tokens=4096
        )


# Singleton Strands Agent
_sql_agent: Optional[Agent] = None


def get_sql_agent(tools=None) -> Agent:
    """
    Get or create the SQL Agent (Strands Agent with MCP tools).

    Args:
        tools: Snowflake MCP tools. If None, gets from MCP manager.

    Returns:
        Strands Agent configured for SQL queries
    """
    global _sql_agent
    if _sql_agent is None:
        if tools is None:
            from agents.shared.snowflake_mcp import get_mcp_manager
            tools = get_mcp_manager().tools

        _sql_agent = Agent(
            model=_get_strands_model(),
            tools=tools,
            system_prompt=_get_system_prompt()
        )
        logger.info("SQL Agent initialized")
    return _sql_agent


class SQLAgent:
    """SQL Agent wrapper for consistent interface."""

    def __init__(self, tools=None):
        self._agent = get_sql_agent(tools)
        self._tools = tools

    async def handle_query(self, query_text: str) -> SQLResult:
        """
        Handle a natural language query about data.

        Args:
            query_text: Natural language question

        Returns:
            SQLResult with data and metadata
        """
        result = await handle_query(query_text, self._tools)

        # Convert to SQLResult
        return SQLResult(
            success=result.get("error") is None,
            sql_query=result.get("sql_query", ""),
            data=result.get("data", []),
            columns=result.get("columns", []),
            row_count=result.get("row_count", 0),
            execution_time_ms=result.get("execution_time_ms", 0),
            error=result.get("error")
        )


async def handle_query(query_text: str, tools=None) -> dict[str, Any]:
    """
    Handle a natural language query about data.

    Args:
        query_text: Natural language question
        tools: Optional MCP tools override

    Returns:
        Response dict with text, data, and metadata
    """
    from agents.shared.artifact_utils import extract_artifacts_from_result

    agent = get_sql_agent(tools)

    try:
        # Strands Agent is synchronous - run in executor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, agent, query_text)

        # Extract text and structured data
        response_text = str(result)
        logger.info(f"SQL agent result type: {type(result).__name__}")

        artifacts = extract_artifacts_from_result(result)

        # Try to parse from text if no artifacts
        if not artifacts and response_text:
            from agents.shared.artifact_utils import _parse_data_from_text
            parsed = _parse_data_from_text(response_text)
            if parsed:
                artifacts.append(parsed)

        # Extract data from artifacts
        data = []
        columns = []
        if artifacts:
            for artifact in artifacts:
                if artifact.get("type") == "table":
                    artifact_data = artifact.get("data", {})
                    data = artifact_data.get("rows", [])
                    columns = artifact_data.get("columns", [])
                    break

        return {
            "text": response_text,
            "agent": "sql",
            "data": data,
            "columns": columns,
            "row_count": len(data),
            "artifacts": artifacts,
            "sql_query": "",  # Would need to extract from agent reasoning
            "execution_time_ms": 0
        }
    except Exception as e:
        logger.error(f"SQL Agent error: {e}")
        return {
            "text": f"Error executing query: {str(e)}",
            "agent": "sql",
            "error": str(e),
            "data": [],
            "columns": [],
            "row_count": 0
        }


async def handle_query_streaming(query_text: str, tools=None):
    """
    Handle a natural language query with streaming events.

    Yields events as the agent processes the query:
    - type: "thinking" - Agent reasoning text
    - type: "tool_call" - Tool being invoked
    - type: "complete" - Final response

    Args:
        query_text: Natural language question
        tools: Optional MCP tools override

    Yields:
        Event dictionaries with type and data
    """
    from agents.shared.artifact_utils import extract_artifacts_from_result

    agent = get_sql_agent(tools)

    try:
        accumulated_text = ""
        tool_call_count = 0
        saw_thinking_since_last_tool = True
        current_tool_name = None

        async for event in agent.stream_async(query_text):
            # Text data (thinking/reasoning)
            if "data" in event:
                text_chunk = event["data"]
                accumulated_text += text_chunk
                saw_thinking_since_last_tool = True
                current_tool_name = None
                yield {
                    "type": "thinking",
                    "agent": "sql",
                    "content": text_chunk,
                    "accumulated": accumulated_text
                }

            # Tool being called
            elif "current_tool_use" in event:
                tool_info = event["current_tool_use"]
                tool_name = tool_info.get("name")
                tool_input = tool_info.get("input", {})

                if tool_name and (saw_thinking_since_last_tool or tool_name != current_tool_name):
                    tool_call_count += 1
                    current_tool_name = tool_name
                    saw_thinking_since_last_tool = False
                    accumulated_text = ""
                    yield {
                        "type": "tool_call",
                        "agent": "sql",
                        "tool": tool_name,
                        "tool_id": tool_call_count,
                        "input": tool_input
                    }

            # Final result
            elif "result" in event:
                result = event["result"]
                response_text = str(result)

                artifacts = extract_artifacts_from_result(result)

                if not artifacts and response_text:
                    from agents.shared.artifact_utils import _parse_data_from_text
                    parsed = _parse_data_from_text(response_text)
                    if parsed:
                        artifacts.append(parsed)

                # Extract data
                data = []
                columns = []
                if artifacts:
                    for artifact in artifacts:
                        if artifact.get("type") == "table":
                            artifact_data = artifact.get("data", {})
                            data = artifact_data.get("rows", [])
                            columns = artifact_data.get("columns", [])
                            break

                yield {
                    "type": "complete",
                    "agent": "sql",
                    "data": {
                        "text": response_text,
                        "agent": "sql",
                        "data": data,
                        "columns": columns,
                        "row_count": len(data),
                        "artifacts": artifacts
                    }
                }

    except Exception as e:
        logger.error(f"SQL Agent streaming error: {e}")
        yield {
            "type": "error",
            "agent": "sql",
            "message": str(e)
        }
        yield {
            "type": "complete",
            "agent": "sql",
            "data": {
                "text": f"Error executing query: {str(e)}",
                "agent": "sql",
                "error": str(e),
                "data": [],
                "columns": [],
                "row_count": 0
            }
        }
