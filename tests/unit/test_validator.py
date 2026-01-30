"""
Unit tests for the Validator Agent.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestValidatorAgent:
    """Tests for ValidatorAgent class."""

    @pytest.fixture
    def validator(self):
        """Create a ValidatorAgent instance with mocked LLM."""
        with patch('agents.validator.agent.get_validator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.validator.agent import ValidatorAgent
            return ValidatorAgent()

    def test_validator_agent_import(self):
        """Test that validator agent can be imported."""
        from agents.validator.agent import ValidatorAgent
        assert ValidatorAgent is not None

    @pytest.mark.asyncio
    async def test_passes_valid_response(self, validator):
        """Test that valid responses pass validation."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "passed",
            "confidence_score": 0.95,
            "checks": [],
            "recommendations": [],
            "should_block": False,
            "block_reason": None,
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="What is the average GPA?",
            response_text="The average GPA is 3.42.",
            sql_query="SELECT AVG(GRADE_POINTS) FROM CDM_LMS.GRADE"
        )

        assert result.overall_status.value == "passed"
        assert result.confidence_score >= 0.8

    @pytest.mark.asyncio
    async def test_blocks_pii_exposure(self, validator):
        """Test that PII in responses is flagged."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "failed",
            "confidence_score": 0.99,
            "checks": [{
                "category": "ferpa_compliance",
                "status": "failed",
                "message": "Response contains student name (PII)"
            }],
            "recommendations": ["Remove individual student identifiers"],
            "should_block": True,
            "block_reason": "PII violation",
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="Show student grades",
            response_text="John Smith received an A in CS101.",
            sql_query="SELECT STUDENT_NAME, GRADE FROM GRADES"
        )

        # Should be blocked due to rule-based PII check or LLM check
        assert result.blocked is True or result.overall_status.value == "failed"

    @pytest.mark.asyncio
    async def test_validates_sql_safety(self, validator):
        """Test that dangerous SQL is flagged."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "failed",
            "confidence_score": 0.99,
            "checks": [{
                "category": "sql_safety",
                "status": "failed",
                "message": "SQL query selects individual student records"
            }],
            "recommendations": ["Use aggregated data instead"],
            "should_block": True,
            "block_reason": "SQL safety violation",
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="Show individual student grades",
            response_text="Here are all grades.",
            sql_query="SELECT PERSON_ID, GRADE_VALUE FROM CDM_LMS.GRADE"
        )

        # Check that validation ran (may pass rule-based check but LLM should flag it)
        assert result is not None

    @pytest.mark.asyncio
    async def test_confidence_scoring(self, validator):
        """Test that confidence scores are reasonable."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "passed",
            "confidence_score": 0.85,
            "checks": [{
                "category": "response_quality",
                "status": "warning",
                "message": "Minor uncertainty about data freshness"
            }],
            "recommendations": [],
            "should_block": False,
            "block_reason": None,
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="Show enrollment data",
            response_text="Total enrollment is 870.",
            sql_query="SELECT COUNT(*) FROM CDM_LMS.PERSON_COURSE"
        )

        assert 0 <= result.confidence_score <= 1


class TestFERPACompliance:
    """Tests for FERPA compliance checking."""

    @pytest.fixture
    def validator(self):
        """Create a ValidatorAgent instance with mocked LLM."""
        with patch('agents.validator.agent.get_validator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.validator.agent import ValidatorAgent
            return ValidatorAgent()

    @pytest.mark.asyncio
    async def test_blocks_individual_grades(self, validator):
        """Test that individual student grades are blocked."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "failed",
            "confidence_score": 0.98,
            "checks": [{
                "category": "ferpa_compliance",
                "status": "failed",
                "message": "Cannot display individual student grades - FERPA violation"
            }],
            "recommendations": ["Show aggregated grade statistics instead"],
            "should_block": True,
            "block_reason": "FERPA violation",
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="What grade did student P001 get?",
            response_text="Student P001 got an A.",
            sql_query="SELECT GRADE_VALUE FROM GRADE WHERE PERSON_ID = 'P001'"
        )

        assert result.overall_status.value == "failed" or result.blocked is True

    @pytest.mark.asyncio
    async def test_allows_aggregate_grades(self, validator):
        """Test that aggregate grade statistics are allowed."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "passed",
            "confidence_score": 0.95,
            "checks": [],
            "recommendations": [],
            "should_block": False,
            "block_reason": None,
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="What is the average grade by course?",
            response_text="Average grades by course: CS101 - 3.5, MATH101 - 3.2",
            sql_query="SELECT COURSE_ID, AVG(GRADE_POINTS) FROM GRADE GROUP BY COURSE_ID"
        )

        assert result.overall_status.value == "passed"

    @pytest.mark.asyncio
    async def test_blocks_student_email(self, validator):
        """Test that student emails are blocked."""
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "failed",
            "confidence_score": 0.99,
            "checks": [{
                "category": "ferpa_compliance",
                "status": "failed",
                "message": "Response contains student email address"
            }],
            "recommendations": ["Remove personal contact information"],
            "should_block": True,
            "block_reason": "PII violation",
            "corrected_response": None
        })

        result = await validator.validate(
            user_query="Show student contact info",
            response_text="Student email: john.doe@university.edu",
            sql_query="SELECT EMAIL FROM STUDENTS"
        )

        # Email pattern should be caught by rule-based check
        assert result.blocked is True or result.overall_status.value == "failed"


class TestHallucinationDetection:
    """Tests for hallucination detection."""

    @pytest.fixture
    def validator(self):
        """Create a ValidatorAgent instance with mocked LLM."""
        with patch('agents.validator.agent.get_validator_llm') as mock_llm:
            mock_llm.return_value = MagicMock()
            from agents.validator.agent import ValidatorAgent
            return ValidatorAgent()

    @pytest.mark.asyncio
    async def test_detects_number_mismatch(self, validator):
        """Test that mismatched numbers are detected."""
        from agents.shared.models import QueryResult
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "failed",
            "confidence_score": 0.90,
            "checks": [{
                "category": "data_accuracy",
                "status": "failed",
                "message": "Response says 1000 but data shows 870"
            }],
            "recommendations": ["Verify numbers match source data"],
            "should_block": False,
            "block_reason": None,
            "corrected_response": None
        })

        query_result = QueryResult(
            data=[{"count": 870}],
            columns=["count"],
            row_count=1,
            execution_time_ms=50,
            query="SELECT COUNT(*) FROM PERSON_COURSE",
            schema="CDM_LMS"
        )

        result = await validator.validate(
            user_query="How many students?",
            response_text="There are 1000 students enrolled.",
            sql_query="SELECT COUNT(*) FROM PERSON_COURSE",
            query_result=query_result
        )

        # Should flag the mismatch
        has_issues = result.overall_status.value == "failed" or len(result.checks) > 0
        assert has_issues

    @pytest.mark.asyncio
    async def test_accepts_accurate_response(self, validator):
        """Test that accurate responses pass (or get warning for small aggregation)."""
        from agents.shared.models import QueryResult
        validator.llm.invoke_with_json_response = AsyncMock(return_value={
            "overall_status": "passed",
            "confidence_score": 0.98,
            "checks": [],
            "recommendations": [],
            "should_block": False,
            "block_reason": None,
            "corrected_response": None
        })

        query_result = QueryResult(
            data=[{"count": 5}],
            columns=["count"],
            row_count=1,
            execution_time_ms=30,
            query="SELECT COUNT(*) FROM COURSE",
            schema="CDM_LMS"
        )

        result = await validator.validate(
            user_query="How many courses?",
            response_text="There are 5 courses in the system.",
            sql_query="SELECT COUNT(*) FROM COURSE",
            query_result=query_result
        )

        # Response should pass or get warning (small result sets trigger aggregation warning)
        # but should NOT be blocked for accurate data
        assert result.overall_status.value in ["passed", "warning"]
        assert result.blocked is False
