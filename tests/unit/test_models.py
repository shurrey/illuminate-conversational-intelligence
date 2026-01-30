"""
Unit tests for shared data models.
"""
import pytest
from agents.shared.models import (
    AgentType, MessageRole, ArtifactType, ChartType, PipelinePath,
    QueryResult, ChartConfig, Artifact, MessagePart, Message,
    ConversationContext, ExecutionPlan, SQLResult, AnalysisResult, WriteResult
)


class TestEnums:
    """Test enum definitions."""

    def test_agent_types(self):
        """Test AgentType enum values."""
        assert AgentType.ORCHESTRATOR.value == "orchestrator"
        assert AgentType.PLANNER.value == "planner"
        assert AgentType.SQL.value == "sql"
        assert AgentType.ANALYST.value == "analyst"
        assert AgentType.WRITER.value == "writer"

    def test_message_roles(self):
        """Test MessageRole enum values."""
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.SYSTEM.value == "system"

    def test_artifact_types(self):
        """Test ArtifactType enum values."""
        assert ArtifactType.TABLE.value == "table"
        assert ArtifactType.CHART.value == "chart"
        assert ArtifactType.TEXT.value == "text"
        assert ArtifactType.ERROR.value == "error"

    def test_pipeline_paths(self):
        """Test PipelinePath enum values."""
        assert PipelinePath.SIMPLE.value == "simple"
        assert PipelinePath.STANDARD.value == "standard"
        assert PipelinePath.DEEP_ANALYSIS.value == "deep"
        assert PipelinePath.VIZ_ONLY.value == "viz_only"


class TestArtifact:
    """Test Artifact model."""

    def test_create_table_artifact(self):
        """Test creating a table artifact."""
        data = [{"name": "Alice"}, {"name": "Bob"}]
        columns = ["name"]
        artifact = Artifact.create_table(data, columns, "Test Table")

        assert artifact.type == ArtifactType.TABLE
        assert artifact.title == "Test Table"
        assert artifact.data["rows"] == data
        assert artifact.data["columns"] == columns
        assert artifact.id is not None

    def test_create_chart_artifact(self):
        """Test creating a chart artifact."""
        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Test Chart",
            x_axis="category",
            y_axis="value",
            data=[{"category": "A", "value": 10}]
        )
        artifact = Artifact.create_chart(config)

        assert artifact.type == ArtifactType.CHART
        assert artifact.title == "Test Chart"
        assert artifact.data["chart_type"] == "bar"

    def test_create_error_artifact(self):
        """Test creating an error artifact."""
        artifact = Artifact.create_error("Something went wrong")

        assert artifact.type == ArtifactType.ERROR
        assert artifact.data == "Something went wrong"

    def test_artifact_to_dict(self):
        """Test artifact serialization."""
        artifact = Artifact.create_text("Hello world", "Greeting")
        d = artifact.to_dict()

        assert d["type"] == "text"
        assert d["title"] == "Greeting"
        assert d["data"] == "Hello world"
        assert "id" in d


class TestMessage:
    """Test Message model."""

    def test_create_user_message(self):
        """Test creating a user message."""
        msg = Message.create_user_message("Hello", "ctx-123")

        assert msg.role == MessageRole.USER
        assert msg.context_id == "ctx-123"
        assert len(msg.parts) == 1
        assert msg.parts[0].content == "Hello"

    def test_create_assistant_message(self):
        """Test creating an assistant message."""
        artifact = Artifact.create_text("Summary", "Summary")
        msg = Message.create_assistant_message(
            "Here is the response",
            "ctx-123",
            artifacts=[artifact]
        )

        assert msg.role == MessageRole.ASSISTANT
        assert len(msg.artifacts) == 1
        assert msg.artifacts[0].type == ArtifactType.TEXT

    def test_message_to_dict(self):
        """Test message serialization."""
        msg = Message.create_user_message("Test", "ctx-123")
        d = msg.to_dict()

        assert d["role"] == "user"
        assert d["context_id"] == "ctx-123"
        assert "timestamp" in d


class TestConversationContext:
    """Test ConversationContext model."""

    def test_create_context(self):
        """Test creating a conversation context."""
        ctx = ConversationContext(id="test-123")

        assert ctx.id == "test-123"
        assert len(ctx.messages) == 0

    def test_add_message(self):
        """Test adding messages to context."""
        ctx = ConversationContext(id="test-123")
        msg = Message.create_user_message("Hello", ctx.id)
        ctx.add_message(msg)

        assert len(ctx.messages) == 1
        assert ctx.messages[0].parts[0].content == "Hello"

    def test_context_to_dict(self):
        """Test context serialization."""
        ctx = ConversationContext(id="test-123")
        d = ctx.to_dict()

        assert d["id"] == "test-123"
        assert "messages" in d
        assert "created_at" in d


class TestExecutionPlan:
    """Test ExecutionPlan model."""

    def test_create_simple_plan(self):
        """Test creating a simple execution plan."""
        plan = ExecutionPlan(
            pipeline_path=PipelinePath.SIMPLE,
            agents_to_call=["sql"],
            skip_validation=True,
            reasoning="Simple count query"
        )

        assert plan.pipeline_path == PipelinePath.SIMPLE
        assert "sql" in plan.agents_to_call
        assert plan.skip_validation is True

    def test_create_standard_plan(self):
        """Test creating a standard execution plan."""
        plan = ExecutionPlan(
            pipeline_path=PipelinePath.STANDARD,
            agents_to_call=["sql", "analyst", "writer"],
            analyst_model="sonnet",
            needs_visualization=True,
            reasoning="Analytical query"
        )

        assert plan.pipeline_path == PipelinePath.STANDARD
        assert plan.analyst_model == "sonnet"
        assert plan.needs_visualization is True

    def test_plan_to_dict(self):
        """Test plan serialization."""
        plan = ExecutionPlan(
            pipeline_path=PipelinePath.DEEP_ANALYSIS,
            agents_to_call=["sql", "analyst", "writer"],
            analyst_model="opus"
        )
        d = plan.to_dict()

        assert d["pipeline_path"] == "deep"
        assert d["analyst_model"] == "opus"


class TestSQLResult:
    """Test SQLResult model."""

    def test_successful_result(self):
        """Test successful SQL result."""
        result = SQLResult(
            success=True,
            sql_query="SELECT * FROM COURSE",
            data=[{"COURSE_ID": "C001"}],
            columns=["COURSE_ID"],
            row_count=1,
            execution_time_ms=150.5
        )

        assert result.success is True
        assert result.row_count == 1
        assert result.error is None

    def test_failed_result(self):
        """Test failed SQL result."""
        result = SQLResult(
            success=False,
            sql_query="SELECT * FROM INVALID",
            data=[],
            columns=[],
            row_count=0,
            execution_time_ms=50.0,
            error="Table not found"
        )

        assert result.success is False
        assert result.error == "Table not found"


class TestAnalysisResult:
    """Test AnalysisResult model."""

    def test_create_analysis(self):
        """Test creating an analysis result."""
        result = AnalysisResult(
            key_insights=["Enrollment is highest in CS department"],
            statistics={"total_enrollment": 870, "avg_gpa": 3.4},
            recommendations=["Consider expanding CS program"]
        )

        assert len(result.key_insights) == 1
        assert result.statistics["total_enrollment"] == 870

    def test_analysis_to_dict(self):
        """Test analysis serialization."""
        result = AnalysisResult(
            key_insights=["Test insight"],
            statistics={"count": 10}
        )
        d = result.to_dict()

        assert "key_insights" in d
        assert "statistics" in d


class TestWriteResult:
    """Test WriteResult model."""

    def test_create_write_result(self):
        """Test creating a write result."""
        artifact = Artifact.create_table(
            [{"a": 1}], ["a"], "Results"
        )
        result = WriteResult(
            text="Here are the results.",
            artifacts=[artifact],
            suggested_followups=["Show me more details"]
        )

        assert "results" in result.text.lower()
        assert len(result.artifacts) == 1
        assert len(result.suggested_followups) == 1
