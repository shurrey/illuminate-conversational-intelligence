"""
Unit tests for the Writer Agent.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.shared.models import AnalysisResult, Artifact, ArtifactType


class TestWriterAgent:
    """Tests for WriterAgent class."""

    @pytest.fixture
    def writer(self):
        """Create a WriterAgent instance with mocked LLM."""
        with patch('agents.writer.agent.get_orchestrator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.writer.agent import WriterAgent
            return WriterAgent()

    def test_writer_agent_import(self):
        """Test that writer agent can be imported."""
        from agents.writer.agent import WriterAgent
        assert WriterAgent is not None

    @pytest.mark.asyncio
    async def test_write_returns_write_result(self, writer):
        """Test that write returns a WriteResult."""
        writer._llm.invoke = AsyncMock(return_value="""The average GPA across all departments is 3.42.

**You might also want to know:**
- Show GPA by department
- What are the trends over time?""")

        analysis = AnalysisResult(
            key_insights=["Average GPA is 3.42"],
            statistics={"avg_gpa": 3.42}
        )

        data = [{"avg_gpa": 3.42}]

        result = await writer.write(
            user_query="What is the average GPA?",
            data=data,
            columns=["avg_gpa"],
            analysis=analysis
        )

        from agents.shared.models import WriteResult
        assert isinstance(result, WriteResult)
        assert "3.42" in result.text
        assert len(result.suggested_followups) > 0

    @pytest.mark.asyncio
    async def test_write_includes_data_table_artifact(self, writer):
        """Test that write includes a data table artifact."""
        writer._llm.invoke = AsyncMock(return_value="""Here is the enrollment by department.

**You might also want to know:**
- Chart this data""")

        analysis = AnalysisResult(
            key_insights=["CS has highest enrollment"],
            statistics={"total": 870}
        )

        data = [
            {"DEPARTMENT": "Computer Science", "ENROLLMENT": 270},
            {"DEPARTMENT": "Mathematics", "ENROLLMENT": 200}
        ]

        result = await writer.write(
            user_query="Show enrollment by department",
            data=data,
            columns=["DEPARTMENT", "ENROLLMENT"],
            analysis=analysis
        )

        # Should include a table artifact
        assert len(result.artifacts) > 0
        table_artifacts = [a for a in result.artifacts if a.type == ArtifactType.TABLE]
        assert len(table_artifacts) > 0

    @pytest.mark.asyncio
    async def test_write_handles_large_datasets(self, writer):
        """Test that writer handles large datasets appropriately."""
        writer._llm.invoke = AsyncMock(return_value="Showing first 100 of 1000 results.")

        analysis = AnalysisResult(
            key_insights=["Large dataset with 1000 rows"],
            statistics={"total_rows": 1000}
        )

        # Create large dataset
        data = [{"id": i, "value": i * 10} for i in range(1000)]

        result = await writer.write(
            user_query="Show all data",
            data=data,
            columns=["id", "value"],
            analysis=analysis
        )

        # Response should mention the large dataset
        assert "100" in result.text or "1000" in result.text


class TestFollowupGeneration:
    """Tests for follow-up question generation."""

    @pytest.fixture
    def writer(self):
        """Create a WriterAgent instance with mocked LLM."""
        with patch('agents.writer.agent.get_orchestrator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.writer.agent import WriterAgent
            return WriterAgent()

    @pytest.mark.asyncio
    async def test_generates_relevant_followups(self, writer):
        """Test that follow-up questions are relevant."""
        writer._llm.invoke = AsyncMock(return_value="""The average GPA is 3.42.

**You might also want to know:**
- How does this compare to last semester?
- Show GPA distribution
- Which department has the highest GPA?""")

        analysis = AnalysisResult(
            key_insights=["Average GPA is 3.42"],
            statistics={"avg_gpa": 3.42}
        )

        result = await writer.write(
            user_query="What is the average GPA?",
            data=[{"avg_gpa": 3.42}],
            columns=["avg_gpa"],
            analysis=analysis
        )

        assert len(result.suggested_followups) >= 2
        # Follow-ups should be questions or actionable
        for followup in result.suggested_followups:
            assert "?" in followup or followup.lower().startswith(("show", "compare", "which"))

    @pytest.mark.asyncio
    async def test_limits_followup_count(self, writer):
        """Test that follow-up count is limited."""
        writer._llm.invoke = AsyncMock(return_value="""Results.

**You might also want to know:**
- Q1?
- Q2?
- Q3?
- Q4?
- Q5?
- Q6?""")

        analysis = AnalysisResult(key_insights=["Test"], statistics={})

        result = await writer.write(
            user_query="Test",
            data=[],
            columns=[],
            analysis=analysis
        )

        # Should not have more than 3 follow-ups (limited in _extract_followups)
        assert len(result.suggested_followups) <= 3


class TestResponseFormatting:
    """Tests for response text formatting."""

    @pytest.fixture
    def writer(self):
        """Create a WriterAgent instance with mocked LLM."""
        with patch('agents.writer.agent.get_orchestrator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.writer.agent import WriterAgent
            return WriterAgent()

    @pytest.mark.asyncio
    async def test_response_is_natural_language(self, writer):
        """Test that response is natural, not technical."""
        writer._llm.invoke = AsyncMock(return_value="Based on the data, Computer Science has the highest enrollment with 270 students, followed by Mathematics with 200 students.")

        analysis = AnalysisResult(
            key_insights=["CS: 270, Math: 200"],
            statistics={"cs": 270, "math": 200}
        )

        result = await writer.write(
            user_query="Which department has the most students?",
            data=[{"dept": "CS", "count": 270}],
            columns=["dept", "count"],
            analysis=analysis
        )

        # Should be readable prose, not just numbers
        assert "Computer Science" in result.text or "highest" in result.text.lower()

    @pytest.mark.asyncio
    async def test_includes_key_numbers(self, writer):
        """Test that response includes key statistics."""
        writer._llm.invoke = AsyncMock(return_value="The total enrollment is 870 students across 5 departments.")

        analysis = AnalysisResult(
            key_insights=["Total: 870"],
            statistics={"total": 870, "departments": 5}
        )

        result = await writer.write(
            user_query="How many students total?",
            data=[{"total": 870}],
            columns=["total"],
            analysis=analysis
        )

        # Should include the actual number
        assert "870" in result.text


class TestArtifactCreation:
    """Tests for artifact creation."""

    @pytest.fixture
    def writer(self):
        """Create a WriterAgent instance with mocked LLM."""
        with patch('agents.writer.agent.get_orchestrator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.writer.agent import WriterAgent
            return WriterAgent()

    @pytest.mark.asyncio
    async def test_creates_table_with_correct_columns(self, writer):
        """Test that table artifact has correct columns."""
        writer._llm.invoke = AsyncMock(return_value="Here is the data.")

        analysis = AnalysisResult(key_insights=[], statistics={})
        data = [
            {"DEPARTMENT": "CS", "COUNT": 270},
            {"DEPARTMENT": "Math", "COUNT": 200}
        ]

        result = await writer.write(
            user_query="Show enrollment",
            data=data,
            columns=["DEPARTMENT", "COUNT"],
            analysis=analysis
        )

        table_artifact = result.artifacts[0]
        assert "DEPARTMENT" in table_artifact.data["columns"]
        assert "COUNT" in table_artifact.data["columns"]

    @pytest.mark.asyncio
    async def test_no_artifact_for_empty_data(self, writer):
        """Test that empty data doesn't create table artifacts."""
        writer._llm.invoke = AsyncMock(return_value="No data found.")

        analysis = AnalysisResult(key_insights=["No data"], statistics={})
        data = []

        result = await writer.write(
            user_query="Show results",
            data=data,
            columns=[],
            analysis=analysis
        )

        # Empty data should not create artifacts
        assert len(result.artifacts) == 0
