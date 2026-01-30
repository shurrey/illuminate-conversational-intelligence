"""
Unit tests for the Analyst Agent.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAnalystAgent:
    """Tests for AnalystAgent class."""

    def test_analyst_agent_import(self):
        """Test that analyst agent can be imported."""
        from agents.analyst.agent import AnalystAgent
        assert AnalystAgent is not None

    @pytest.mark.asyncio
    async def test_analyze_returns_analysis_result(self):
        """Test that analyze returns an AnalysisResult."""
        mock_llm = MagicMock()
        mock_llm.invoke_with_json_response = AsyncMock(return_value={
            "key_insights": ["CS has highest enrollment"],
            "statistics": {"total_enrollment": 870, "departments": 5},
            "trends": [],
            "anomalies": [],
            "recommendations": ["Consider expanding CS"],
            "educational_context": "Higher education setting",
            "visualization_suggestion": {
                "type": "bar",
                "x": "department",
                "y": "enrollment"
            }
        })

        with patch('agents.analyst.agent.get_orchestrator_llm', return_value=mock_llm):
            from agents.analyst.agent import AnalystAgent
            analyst = AnalystAgent()

            data = [
                {"DEPARTMENT": "Computer Science", "ENROLLMENT": 270},
                {"DEPARTMENT": "Mathematics", "ENROLLMENT": 200}
            ]

            result = await analyst.analyze(
                user_query="Show enrollment by department",
                data=data,
                columns=["DEPARTMENT", "ENROLLMENT"],
                model="sonnet"
            )

            from agents.shared.models import AnalysisResult
            assert isinstance(result, AnalysisResult)
            assert len(result.key_insights) > 0
            assert "total_enrollment" in result.statistics

    @pytest.mark.asyncio
    async def test_analyze_handles_empty_data(self):
        """Test that analyze handles empty data gracefully."""
        mock_llm = MagicMock()
        mock_llm.invoke_with_json_response = AsyncMock(return_value={
            "key_insights": ["No data available for analysis"],
            "statistics": {},
            "trends": [],
            "anomalies": [],
            "recommendations": ["Check query or data source"],
            "educational_context": "",
            "visualization_suggestion": None
        })

        with patch('agents.analyst.agent.get_orchestrator_llm', return_value=mock_llm):
            from agents.analyst.agent import AnalystAgent
            analyst = AnalystAgent()

            result = await analyst.analyze(
                user_query="Show enrollment",
                data=[],
                columns=[],
                model="sonnet"
            )

            assert len(result.key_insights) > 0

    @pytest.mark.asyncio
    async def test_model_selection_sonnet(self):
        """Test that model selection for sonnet works."""
        mock_llm = MagicMock()
        mock_llm.invoke_with_json_response = AsyncMock(return_value={
            "key_insights": ["Test"],
            "statistics": {},
            "trends": [],
            "anomalies": [],
            "recommendations": [],
            "educational_context": "",
            "visualization_suggestion": None
        })

        with patch('agents.analyst.agent.get_orchestrator_llm', return_value=mock_llm) as mock_get_llm:
            from agents.analyst.agent import AnalystAgent
            analyst = AnalystAgent()

            await analyst.analyze(
                user_query="Test query",
                data=[{"a": 1}],
                columns=["a"],
                model="sonnet"
            )

            # Verify get_orchestrator_llm was called (sonnet model)
            mock_get_llm.assert_called_once_with(caller="ANALYST")
            mock_llm.invoke_with_json_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_model_selection_opus(self):
        """Test that model selection for opus works."""
        mock_llm = MagicMock()
        mock_llm.invoke_with_json_response = AsyncMock(return_value={
            "key_insights": ["Deep analysis"],
            "statistics": {},
            "trends": [],
            "anomalies": [],
            "recommendations": [],
            "educational_context": "",
            "visualization_suggestion": None
        })

        with patch('agents.analyst.agent.get_worker_llm', return_value=mock_llm) as mock_get_llm:
            from agents.analyst.agent import AnalystAgent
            analyst = AnalystAgent()

            await analyst.analyze(
                user_query="Test query",
                data=[{"a": 1}],
                columns=["a"],
                model="opus"
            )

            # Verify get_worker_llm was called (opus model)
            mock_get_llm.assert_called_once_with(caller="ANALYST")


class TestAnalystParsing:
    """Tests for analysis result parsing."""

    def test_parse_full_result(self):
        """Test parsing a complete analysis result."""
        from agents.analyst.agent import AnalystAgent
        analyst = AnalystAgent()

        raw = {
            "key_insights": ["Insight 1", "Insight 2"],
            "statistics": {"mean": 3.5, "count": 100},
            "trends": [{"direction": "up", "metric": "enrollment"}],
            "anomalies": [{"type": "outlier", "value": 99}],
            "recommendations": ["Rec 1"],
            "educational_context": "University setting",
            "visualization_suggestion": {"type": "line"}
        }

        result = analyst._parse_analysis(raw)

        assert len(result.key_insights) == 2
        assert result.statistics["mean"] == 3.5
        assert len(result.trends) == 1
        assert len(result.anomalies) == 1

    def test_parse_minimal_result(self):
        """Test parsing with minimal fields."""
        from agents.analyst.agent import AnalystAgent
        analyst = AnalystAgent()

        raw = {
            "key_insights": ["Only one insight"],
            "statistics": {}
        }

        result = analyst._parse_analysis(raw)

        assert len(result.key_insights) == 1
        assert result.trends == []
        assert result.recommendations == []

    def test_parse_handles_missing_fields(self):
        """Test that missing fields use defaults."""
        from agents.analyst.agent import AnalystAgent
        analyst = AnalystAgent()

        raw = {}

        result = analyst._parse_analysis(raw)

        assert result.key_insights == []
        assert result.statistics == {}


class TestVisualizationSuggestion:
    """Tests for visualization suggestion logic."""

    @pytest.mark.asyncio
    async def test_suggests_bar_chart_for_categories(self):
        """Test that categorical data suggests bar chart."""
        mock_llm = MagicMock()
        mock_llm.invoke_with_json_response = AsyncMock(return_value={
            "key_insights": ["Data shows categorical comparison"],
            "statistics": {"categories": 5},
            "trends": [],
            "anomalies": [],
            "recommendations": [],
            "educational_context": "",
            "visualization_suggestion": {
                "type": "bar",
                "x": "category",
                "y": "value",
                "reasoning": "Comparing discrete categories"
            }
        })

        with patch('agents.analyst.agent.get_orchestrator_llm', return_value=mock_llm):
            from agents.analyst.agent import AnalystAgent
            analyst = AnalystAgent()

            data = [
                {"category": "A", "value": 10},
                {"category": "B", "value": 20}
            ]

            result = await analyst.analyze(
                user_query="Compare values by category",
                data=data,
                columns=["category", "value"],
                model="sonnet"
            )

            assert result.visualization_suggestion is not None
            assert result.visualization_suggestion["type"] == "bar"

    @pytest.mark.asyncio
    async def test_no_visualization_for_single_value(self):
        """Test that single values don't suggest visualization."""
        mock_llm = MagicMock()
        mock_llm.invoke_with_json_response = AsyncMock(return_value={
            "key_insights": ["The average GPA is 3.42"],
            "statistics": {"average_gpa": 3.42},
            "trends": [],
            "anomalies": [],
            "recommendations": [],
            "educational_context": "",
            "visualization_suggestion": None
        })

        with patch('agents.analyst.agent.get_orchestrator_llm', return_value=mock_llm):
            from agents.analyst.agent import AnalystAgent
            analyst = AnalystAgent()

            data = [{"avg_gpa": 3.42}]

            result = await analyst.analyze(
                user_query="What is the average GPA?",
                data=data,
                columns=["avg_gpa"],
                model="sonnet"
            )

            assert result.visualization_suggestion is None
