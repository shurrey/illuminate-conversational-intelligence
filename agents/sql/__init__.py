"""
SQL Agent - Generates and executes SQL queries against Snowflake.

Uses Strands Agent framework with Snowflake MCP tools to:
- Understand natural language questions
- Generate appropriate SQL queries
- Execute queries and return structured results
"""
from agents.sql.agent import SQLAgent, get_sql_agent, handle_query, handle_query_streaming

__all__ = ["SQLAgent", "get_sql_agent", "handle_query", "handle_query_streaming"]
