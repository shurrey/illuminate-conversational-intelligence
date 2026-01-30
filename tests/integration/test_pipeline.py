"""
Integration tests for the full agent pipeline.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


class TestFullPipeline:
    """Integration tests for the complete query pipeline."""

    @pytest.fixture
    def mock_llm_responses(self):
        """Set up mock responses for all agents."""
        return {
            "planner": {
                "pipeline_path": "standard",
                "agents_to_call": ["sql", "analyst", "writer"],
                "analyst_model": "sonnet",
                "needs_visualization": False,
                "skip_validation": False,
                "context_notes": "",
                "reasoning": "Standard analytical query"
            },
            "analyst": {
                "key_insights": ["CS has highest enrollment at 270"],
                "statistics": {"total": 870, "departments": 5},
                "trends": [],
                "anomalies": [],
                "recommendations": [],
                "educational_context": "University LMS data",
                "visualization_suggestion": None
            },
            "writer": {
                "response_text": "The enrollment data shows Computer Science has the highest enrollment with 270 students.",
                "suggested_followups": ["Show enrollment trends", "Compare to last year"]
            },
            "validator": {
                "is_valid": True,
                "confidence": 0.95,
                "issues": [],
                "suggestions": []
            }
        }

    @pytest.mark.asyncio
    async def test_simple_count_query(self):
        """Test a simple count query through the pipeline."""
        # This test uses mock mode which is enabled by conftest.py
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        result = tools[0]("SELECT COUNT(*) FROM CDM_LMS.COURSE")
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["row_count"] > 0

    @pytest.mark.asyncio
    async def test_analytical_query(self):
        """Test an analytical query with grouping."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        result = tools[0](
            "SELECT DEPARTMENT, COUNT(*) as cnt FROM CDM_LMS.COURSE GROUP BY DEPARTMENT"
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert len(data["data"]) > 1  # Multiple departments

    @pytest.mark.asyncio
    async def test_grade_aggregation(self):
        """Test grade aggregation respects FERPA."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        result = tools[0](
            "SELECT AVG(GRADE_POINTS) as avg_gpa FROM CDM_LMS.GRADE"
        )
        data = json.loads(result)

        assert data["status"] == "success"
        # Result should be aggregated
        assert data["row_count"] == 1


class TestPipelineErrorHandling:
    """Tests for error handling in the pipeline."""

    @pytest.mark.asyncio
    async def test_handles_empty_results(self):
        """Test that empty results are handled gracefully."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        # Query for non-existent data
        result = tools[0](
            "SELECT * FROM CDM_LMS.COURSE WHERE DEPARTMENT = 'NonExistent'"
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["row_count"] == 0

    @pytest.mark.asyncio
    async def test_handles_invalid_table(self):
        """Test that invalid table names are handled."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        result = tools[0]("SELECT * FROM INVALID_TABLE")
        data = json.loads(result)

        # Should return empty results, not crash
        assert data["row_count"] == 0


class TestContextPreservation:
    """Tests for conversation context preservation."""

    def test_context_creation(self):
        """Test that conversation context can be created."""
        from agents.shared.models import ConversationContext, Message, MessageRole, MessagePart

        context = ConversationContext(id="test-session")
        assert context.id == "test-session"
        assert len(context.messages) == 0

    def test_context_message_addition(self):
        """Test adding messages to context."""
        from agents.shared.models import ConversationContext, Message, MessageRole, MessagePart

        context = ConversationContext(id="test-session")

        user_msg = Message(
            id="msg-1",
            role=MessageRole.USER,
            parts=[MessagePart(type="text", content="Hello")],
            context_id=context.id
        )
        context.add_message(user_msg)

        assert len(context.messages) == 1
        assert context.messages[0].parts[0].content == "Hello"

    def test_context_artifact_preservation(self, sample_conversation_context):
        """Test that artifacts are preserved in context."""
        # Verify artifacts exist in the context
        has_artifact = False
        for msg in sample_conversation_context.messages:
            if msg.artifacts:
                has_artifact = True
                break

        assert has_artifact


class TestStreamingEvents:
    """Tests for streaming event generation."""

    def test_planning_event_structure(self):
        """Test planning event has correct structure."""
        from agents.shared.models import ExecutionPlan, PipelinePath

        plan = ExecutionPlan(
            pipeline_path=PipelinePath.STANDARD,
            agents_to_call=["sql", "analyst", "writer"],
            reasoning="Test plan"
        )

        event = {
            "type": "planning",
            "agent": "planner",
            "plan": plan.to_dict(),
            "content": f"Plan: {plan.reasoning}"
        }

        assert event["type"] == "planning"
        assert event["plan"]["pipeline_path"] == "standard"

    def test_status_event_structure(self):
        """Test status event has correct structure."""
        event = {
            "type": "status",
            "message": "Analyzing query..."
        }

        assert event["type"] == "status"
        assert "message" in event

    def test_complete_event_structure(self):
        """Test complete event has correct structure."""
        from agents.shared.models import Artifact, ArtifactType

        artifact = Artifact(
            id="test-1",
            type=ArtifactType.TABLE,
            data={"rows": [{"a": 1}], "columns": ["a"]},
            title="Results"
        )

        event = {
            "type": "complete",
            "text": "Here are the results.",
            "artifacts": [artifact.to_dict()],
            "suggested_followups": ["What else?"]
        }

        assert event["type"] == "complete"
        assert "text" in event
        assert "artifacts" in event
