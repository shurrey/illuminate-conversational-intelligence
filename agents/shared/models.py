"""
Shared data models for Illuminate Conversational Intelligence agents.
"""
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
from datetime import datetime
import uuid


class AgentType(Enum):
    """Types of specialist agents in the system."""
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    SQL = "sql"
    ANALYST = "analyst"
    WRITER = "writer"
    VISUALIZATION = "visualization"
    VALIDATOR = "validator"


class MessageRole(Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ArtifactType(Enum):
    """Types of artifacts that can be returned by agents."""
    TABLE = "table"
    CHART = "chart"
    TEXT = "text"
    ERROR = "error"


class ChartType(Enum):
    """Supported chart types for visualization."""
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    HISTOGRAM = "histogram"


@dataclass
class QueryResult:
    """Result from a Snowflake query."""
    data: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    execution_time_ms: float
    query: str
    schema: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "columns": self.columns,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "query": self.query,
            "schema": self.schema
        }


@dataclass
class ChartConfig:
    """Configuration for generating a chart."""
    chart_type: ChartType
    title: str
    x_axis: str
    y_axis: str
    data: list[dict[str, Any]]
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    color_by: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_type": self.chart_type.value,
            "title": self.title,
            "x_axis": self.x_axis,
            "y_axis": self.y_axis,
            "data": self.data,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "color_by": self.color_by
        }


@dataclass
class Artifact:
    """An artifact (table, chart, etc.) returned by an agent."""
    id: str
    type: ArtifactType
    data: Any
    title: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def create_table(cls, data: list[dict], columns: list[str], title: str = "Results") -> "Artifact":
        return cls(
            id=str(uuid.uuid4()),
            type=ArtifactType.TABLE,
            data={"rows": data, "columns": columns},
            title=title
        )

    @classmethod
    def create_chart(cls, config: ChartConfig) -> "Artifact":
        return cls(
            id=str(uuid.uuid4()),
            type=ArtifactType.CHART,
            data=config.to_dict(),
            title=config.title
        )

    @classmethod
    def create_text(cls, text: str, title: str = "Summary") -> "Artifact":
        return cls(
            id=str(uuid.uuid4()),
            type=ArtifactType.TEXT,
            data=text,
            title=title
        )

    @classmethod
    def create_error(cls, error: str) -> "Artifact":
        return cls(
            id=str(uuid.uuid4()),
            type=ArtifactType.ERROR,
            data=error,
            title="Error"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "data": self.data,
            "title": self.title,
            "description": self.description
        }


@dataclass
class MessagePart:
    """A part of a message (text or artifact reference)."""
    type: str  # "text" or "artifact"
    content: str | dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content
        }


@dataclass
class Message:
    """A message in a conversation."""
    id: str
    role: MessageRole
    parts: list[MessagePart]
    artifacts: list[Artifact] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    context_id: Optional[str] = None

    @classmethod
    def create_user_message(cls, text: str, context_id: str) -> "Message":
        return cls(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            parts=[MessagePart(type="text", content=text)],
            context_id=context_id
        )

    @classmethod
    def create_assistant_message(
        cls,
        text: str,
        context_id: str,
        artifacts: list[Artifact] = None
    ) -> "Message":
        return cls(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            parts=[MessagePart(type="text", content=text)],
            artifacts=artifacts or [],
            context_id=context_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "parts": [p.to_dict() for p in self.parts],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "timestamp": self.timestamp.isoformat(),
            "context_id": self.context_id
        }


@dataclass
class AgentCard:
    """A2A Agent Card describing agent capabilities."""
    name: str
    description: str
    protocol_version: str = "0.3"
    capabilities: dict[str, bool] = field(default_factory=lambda: {"streaming": True})
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text", "data"])
    skills: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities,
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": self.skills
        }


@dataclass
class A2ATask:
    """An A2A task sent between agents."""
    id: str
    message: Message
    source_agent: str
    target_agent: str
    status: str = "pending"  # pending, in_progress, completed, failed
    result: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message": self.message.to_dict(),
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "status": self.status,
            "result": self.result
        }


@dataclass
class ConversationContext:
    """Context for a conversation session."""
    id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class User:
    """User information for authentication."""
    id: str
    name: str
    role: str
    permissions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "permissions": self.permissions
        }


# Domain-specific query intent types
class QueryIntent(Enum):
    """Intent types for query routing."""
    # Learning domain (CDM_LMS)
    COURSE_ANALYTICS = "course_analytics"
    GRADE_ANALYSIS = "grade_analysis"
    ENROLLMENT_QUERIES = "enrollment_queries"
    ASSIGNMENT_ANALYTICS = "assignment_analytics"

    # Visualization
    CHART_GENERATION = "chart_generation"
    DATA_SUMMARIZATION = "data_summarization"
    EXPORT_FORMATTING = "export_formatting"
    VISUALIZATION_ONLY = "visualization_only"  # For visualizing existing data from context

    # General
    CLARIFICATION = "clarification"
    UNKNOWN = "unknown"


@dataclass
class RoutingDecision:
    """Decision about which agent(s) to route a query to."""
    primary_agent: AgentType
    secondary_agents: list[AgentType] = field(default_factory=list)
    intent: QueryIntent = QueryIntent.UNKNOWN
    requires_visualization: bool = False
    confidence: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_agent": self.primary_agent.value,
            "secondary_agents": [a.value for a in self.secondary_agents],
            "intent": self.intent.value,
            "requires_visualization": self.requires_visualization,
            "confidence": self.confidence,
            "reasoning": self.reasoning
        }


# Pipeline models for new agent architecture

class PipelinePath(Enum):
    """Pipeline execution paths."""
    SIMPLE = "simple"              # SQL → format response (no analysis)
    STANDARD = "standard"          # SQL → Analyst → Writer
    DEEP_ANALYSIS = "deep"         # SQL → Analyst(Opus) → Writer
    VIZ_ONLY = "viz_only"          # Context data → Visualization
    CLARIFICATION = "clarification"  # No data needed


@dataclass
class ExecutionPlan:
    """Plan created by Planner Agent for query execution."""
    pipeline_path: PipelinePath
    agents_to_call: list[str]       # ["sql", "analyst", "writer"]
    analyst_model: str = "sonnet"   # "sonnet" or "opus"
    needs_visualization: bool = False
    skip_validation: bool = False   # True for simple queries
    context_notes: str = ""         # Relevant context for agents
    reasoning: str = ""             # Why this plan was chosen

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_path": self.pipeline_path.value,
            "agents_to_call": self.agents_to_call,
            "analyst_model": self.analyst_model,
            "needs_visualization": self.needs_visualization,
            "skip_validation": self.skip_validation,
            "context_notes": self.context_notes,
            "reasoning": self.reasoning
        }


@dataclass
class SQLResult:
    """Result from SQL Agent query execution."""
    success: bool
    sql_query: str
    data: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    execution_time_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "sql_query": self.sql_query,
            "data": self.data,
            "columns": self.columns,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error
        }


@dataclass
class AnalysisResult:
    """Result from Analyst Agent data interpretation."""
    key_insights: list[str]
    statistics: dict[str, Any]
    trends: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    educational_context: str = ""
    visualization_suggestion: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_insights": self.key_insights,
            "statistics": self.statistics,
            "trends": self.trends,
            "anomalies": self.anomalies,
            "recommendations": self.recommendations,
            "educational_context": self.educational_context,
            "visualization_suggestion": self.visualization_suggestion
        }


@dataclass
class WriteResult:
    """Result from Writer Agent response crafting."""
    text: str
    artifacts: list[Artifact] = field(default_factory=list)
    suggested_followups: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "suggested_followups": self.suggested_followups
        }
