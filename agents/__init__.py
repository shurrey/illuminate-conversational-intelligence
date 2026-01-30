"""
Illuminate Conversational Intelligence - Multi-Agent System

This package contains the multi-agent system for natural language access
to Anthology Illuminate's educational data warehouse.

Architecture (Pipeline):
    User Query → Planner (Opus) → Orchestrator executes plan
                                   ├── SQL Agent → Orchestrator
                                   ├── Analyst Agent → Orchestrator
                                   ├── Writer Agent → Orchestrator
                                   ├── Visualization Agent → Orchestrator
                                   └── Validator Agent → Orchestrator
                                   → Final Response

Agents:
- Orchestrator: Central coordinator, executes plans from Planner
- Planner: Creates execution plans using Opus for reasoning
- SQL Agent: Generates and executes SQL via Snowflake MCP
- Analyst Agent: Interprets data, finds patterns and insights
- Writer Agent: Crafts natural language responses
- Visualization Agent: Chart and export specialist
- Validator Agent: FERPA compliance and response validation

Usage:
    from agents.orchestrator.agent import query

    result = await query("What is the average GPA for Fall 2024?")
    print(result["text"])
"""
from agents.orchestrator.agent import query, get_orchestrator_agent
from agents.planner.agent import get_planner_agent
from agents.sql.agent import handle_query as sql_query
from agents.analyst.agent import get_analyst_agent
from agents.writer.agent import get_writer_agent

__all__ = [
    "query",
    "get_orchestrator_agent",
    "get_planner_agent",
    "sql_query",
    "get_analyst_agent",
    "get_writer_agent"
]
__version__ = "0.1.0"
