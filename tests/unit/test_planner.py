"""
Unit tests for the Planner Agent.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.shared.models import PipelinePath, ExecutionPlan, ConversationContext


class TestPlannerAgent:
    """Tests for PlannerAgent class."""

    @pytest.fixture
    def planner(self):
        """Create a PlannerAgent instance with mocked LLM."""
        with patch('agents.planner.agent.get_worker_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.planner.agent import PlannerAgent
            return PlannerAgent()

    @pytest.mark.asyncio
    async def test_simple_query_returns_simple_path(self, planner):
        """Test that simple queries get SIMPLE pipeline path."""
        planner._llm.invoke_with_json_response = AsyncMock(return_value={
            "pipeline_path": "simple",
            "agents_to_call": ["sql"],
            "analyst_model": "sonnet",
            "needs_visualization": False,
            "skip_validation": True,
            "context_notes": "",
            "reasoning": "Simple count query"
        })

        plan = await planner.create_plan("How many courses are there?")

        assert plan.pipeline_path == PipelinePath.SIMPLE
        assert "sql" in plan.agents_to_call
        assert plan.skip_validation is True

    @pytest.mark.asyncio
    async def test_analytical_query_returns_standard_path(self, planner):
        """Test that analytical queries get STANDARD pipeline path."""
        planner._llm.invoke_with_json_response = AsyncMock(return_value={
            "pipeline_path": "standard",
            "agents_to_call": ["sql", "analyst", "writer"],
            "analyst_model": "sonnet",
            "needs_visualization": False,
            "skip_validation": False,
            "context_notes": "",
            "reasoning": "Analytical query requiring interpretation"
        })

        plan = await planner.create_plan("What is the average GPA by department?")

        assert plan.pipeline_path == PipelinePath.STANDARD
        assert "analyst" in plan.agents_to_call
        assert "writer" in plan.agents_to_call

    @pytest.mark.asyncio
    async def test_complex_query_returns_deep_analysis_path(self, planner):
        """Test that complex queries get DEEP_ANALYSIS pipeline path."""
        planner._llm.invoke_with_json_response = AsyncMock(return_value={
            "pipeline_path": "deep",
            "agents_to_call": ["sql", "analyst", "writer"],
            "analyst_model": "opus",
            "needs_visualization": True,
            "skip_validation": False,
            "context_notes": "",
            "reasoning": "Complex trend analysis"
        })

        plan = await planner.create_plan("What trends do you see in student retention over the past 3 years?")

        assert plan.pipeline_path == PipelinePath.DEEP_ANALYSIS
        assert plan.analyst_model == "opus"
        assert plan.needs_visualization is True

    @pytest.mark.asyncio
    async def test_visualization_request_returns_viz_only_path(self, planner):
        """Test that visualization requests get VIZ_ONLY pipeline path."""
        planner._llm.invoke_with_json_response = AsyncMock(return_value={
            "pipeline_path": "viz_only",
            "agents_to_call": ["visualization"],
            "analyst_model": "sonnet",
            "needs_visualization": True,
            "skip_validation": True,
            "context_notes": "Previous response contains enrollment data",
            "reasoning": "User wants to visualize existing data"
        })

        # Include context with previous data
        context = ConversationContext(id="test-123")
        plan = await planner.create_plan("Chart that", context)

        assert plan.pipeline_path == PipelinePath.VIZ_ONLY
        assert "visualization" in plan.agents_to_call

    @pytest.mark.asyncio
    async def test_error_returns_default_plan(self, planner):
        """Test that LLM errors result in a safe default plan."""
        planner._llm.invoke_with_json_response = AsyncMock(
            side_effect=Exception("LLM unavailable")
        )

        plan = await planner.create_plan("What is the average GPA?")

        # Should return safe defaults
        assert plan.pipeline_path == PipelinePath.STANDARD
        assert plan.agents_to_call == ["sql", "analyst", "writer"]
        assert "error" in plan.reasoning.lower()


class TestPlannerParsing:
    """Tests for plan parsing logic."""

    @pytest.fixture
    def planner(self):
        """Create a PlannerAgent instance with mocked LLM."""
        with patch('agents.planner.agent.get_worker_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.planner.agent import PlannerAgent
            return PlannerAgent()

    def test_parse_simple_path(self, planner):
        """Test parsing simple pipeline path."""
        result = {"pipeline_path": "simple", "agents_to_call": ["sql"]}
        plan = planner._parse_plan(result)
        assert plan.pipeline_path == PipelinePath.SIMPLE

    def test_parse_deep_analysis_path(self, planner):
        """Test parsing deep_analysis pipeline path."""
        result = {"pipeline_path": "deep_analysis", "agents_to_call": ["sql", "analyst"]}
        plan = planner._parse_plan(result)
        assert plan.pipeline_path == PipelinePath.DEEP_ANALYSIS

    def test_parse_unknown_path_defaults_to_standard(self, planner):
        """Test that unknown paths default to STANDARD."""
        result = {"pipeline_path": "unknown", "agents_to_call": ["sql"]}
        plan = planner._parse_plan(result)
        assert plan.pipeline_path == PipelinePath.STANDARD

    def test_parse_missing_fields_use_defaults(self, planner):
        """Test that missing fields use sensible defaults."""
        result = {"pipeline_path": "standard"}
        plan = planner._parse_plan(result)

        assert plan.agents_to_call == ["sql", "analyst", "writer"]
        assert plan.analyst_model == "sonnet"
        assert plan.needs_visualization is False


class TestContextBuilding:
    """Tests for conversation context handling."""

    @pytest.fixture
    def planner(self):
        """Create a PlannerAgent instance with mocked LLM."""
        with patch('agents.planner.agent.get_worker_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.planner.agent import PlannerAgent
            return PlannerAgent()

    def test_build_context_summary_no_context(self, planner):
        """Test context summary with no previous context."""
        summary = planner._build_context_summary(None)
        assert "No previous conversation" in summary

    def test_build_context_summary_with_messages(self, planner, sample_conversation_context):
        """Test context summary includes recent messages."""
        summary = planner._build_context_summary(sample_conversation_context)

        assert "CONTEXT:" in summary
        assert "USER:" in summary or "ASSISTANT:" in summary

    def test_build_context_summary_detects_data_artifacts(self, planner, sample_conversation_context):
        """Test that context summary notes presence of data tables."""
        summary = planner._build_context_summary(sample_conversation_context)

        # Should mention that previous response has data
        assert "data table" in summary.lower() or "table" in summary.lower()
