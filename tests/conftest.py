"""
Pytest configuration and fixtures for Illuminate CI tests.
"""
import os
import pytest
from unittest.mock import MagicMock, AsyncMock

# Force mock mode for all tests
os.environ["ILLUMINATE_MOCK_MODE"] = "true"


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    def _create_response(content: dict):
        mock = MagicMock()
        mock.content = content
        return mock
    return _create_response


@pytest.fixture
def sample_query_result():
    """Sample SQL query result for testing."""
    return {
        "data": [
            {"DEPARTMENT": "Computer Science", "ENROLLMENT_COUNT": 270, "AVG_GRADE": 3.5},
            {"DEPARTMENT": "Mathematics", "ENROLLMENT_COUNT": 200, "AVG_GRADE": 3.2},
            {"DEPARTMENT": "English", "ENROLLMENT_COUNT": 180, "AVG_GRADE": 3.7},
        ],
        "columns": ["DEPARTMENT", "ENROLLMENT_COUNT", "AVG_GRADE"],
        "row_count": 3,
    }


@pytest.fixture
def sample_conversation_context():
    """Sample conversation context for testing follow-ups."""
    from agents.shared.models import (
        ConversationContext, Message, MessageRole, MessagePart, Artifact, ArtifactType
    )

    context = ConversationContext(id="test-session-123")

    # Add a previous exchange
    user_msg = Message(
        id="msg-1",
        role=MessageRole.USER,
        parts=[MessagePart(type="text", content="What is the enrollment by department?")],
        context_id=context.id
    )
    context.add_message(user_msg)

    assistant_msg = Message(
        id="msg-2",
        role=MessageRole.ASSISTANT,
        parts=[MessagePart(type="text", content="Here is the enrollment by department...")],
        artifacts=[
            Artifact(
                id="artifact-1",
                type=ArtifactType.TABLE,
                data={
                    "rows": [
                        {"DEPARTMENT": "Computer Science", "ENROLLMENT_COUNT": 270},
                        {"DEPARTMENT": "Mathematics", "ENROLLMENT_COUNT": 200},
                    ],
                    "columns": ["DEPARTMENT", "ENROLLMENT_COUNT"]
                },
                title="Enrollment by Department"
            )
        ],
        context_id=context.id
    )
    context.add_message(assistant_msg)

    return context


@pytest.fixture
def mock_snowflake_tools():
    """Mock Snowflake MCP tools for testing."""
    async def mock_read_query(query: str):
        # Return mock data based on query content
        if "COUNT" in query.upper():
            return '{"data": [{"count": 5}], "columns": ["count"], "row_count": 1}'
        elif "AVG" in query.upper():
            return '{"data": [{"avg_grade_points": 3.42}], "columns": ["avg_grade_points"], "row_count": 1}'
        else:
            return '{"data": [], "columns": [], "row_count": 0}'

    async def mock_list_tables(schema_name: str = ""):
        return '[{"schema": "CDM_LMS", "table_name": "COURSE"}, {"schema": "CDM_LMS", "table_name": "GRADE"}]'

    async def mock_describe_table(table_name: str):
        return '{"table": "CDM_LMS.COURSE", "columns": [{"COLUMN_NAME": "COURSE_ID"}]}'

    return {
        "read_query": mock_read_query,
        "list_tables": mock_list_tables,
        "describe_table": mock_describe_table,
    }
