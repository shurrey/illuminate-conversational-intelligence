"""
Shared utilities for Illuminate agents.
"""
from .models import (
    AgentType, MessageRole, ArtifactType, ChartType,
    QueryResult, ChartConfig, Artifact, MessagePart,
    Message, AgentCard, A2ATask, ConversationContext,
    User, QueryIntent, RoutingDecision
)
from .snowflake_mcp import (
    SnowflakeMCPManager, get_mcp_manager, is_mock_mode
)
from .a2a_client import (
    A2AClient, A2AServer, A2AConfig, TaskStatus,
    LocalAgentRegistry, get_agent_registry
)

__all__ = [
    # Models
    "AgentType", "MessageRole", "ArtifactType", "ChartType",
    "QueryResult", "ChartConfig", "Artifact", "MessagePart",
    "Message", "AgentCard", "A2ATask", "ConversationContext",
    "User", "QueryIntent", "RoutingDecision",
    # MCP
    "SnowflakeMCPManager", "get_mcp_manager", "is_mock_mode",
    # A2A
    "A2AClient", "A2AServer", "A2AConfig", "TaskStatus",
    "LocalAgentRegistry", "get_agent_registry"
]
