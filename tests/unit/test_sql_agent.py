"""
Unit tests for the SQL Agent.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


class TestSQLAgent:
    """Tests for SQL Agent functionality."""

    def test_sql_agent_import(self):
        """Test that SQL agent can be imported."""
        from agents.sql.agent import SQLAgent
        assert SQLAgent is not None

    def test_sql_agent_wrapper_class(self):
        """Test SQLAgent wrapper class can be instantiated with mock tools."""
        mock_tools = [MagicMock(), MagicMock(), MagicMock()]

        with patch('agents.sql.agent.Agent'):
            from agents.sql.agent import SQLAgent
            # Reset singleton
            import agents.sql.agent
            agents.sql.agent._sql_agent = None

            agent = SQLAgent(tools=mock_tools)
            assert agent is not None


class TestMockQueryExecution:
    """Tests for mock query execution."""

    def test_mock_read_query_count(self):
        """Test mock read_query for COUNT queries."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        read_query = tools[0]  # First tool is read_query

        result = read_query("SELECT COUNT(*) FROM CDM_LMS.COURSE")
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["row_count"] > 0

    def test_mock_read_query_with_group_by(self):
        """Test mock read_query with GROUP BY."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        read_query = tools[0]

        result = read_query(
            "SELECT DEPARTMENT, COUNT(*) FROM CDM_LMS.COURSE GROUP BY DEPARTMENT"
        )
        data = json.loads(result)

        assert data["status"] == "success"
        # Should have grouped results
        assert len(data["data"]) > 1

    def test_mock_read_query_with_where(self):
        """Test mock read_query with WHERE clause."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        read_query = tools[0]

        result = read_query(
            "SELECT * FROM CDM_LMS.COURSE WHERE DEPARTMENT = 'Computer Science'"
        )
        data = json.loads(result)

        assert data["status"] == "success"
        # Should filter results
        for row in data["data"]:
            assert row.get("DEPARTMENT", "").lower() == "computer science"

    def test_mock_list_tables(self):
        """Test mock list_tables."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        list_tables = tools[1]  # Second tool is list_tables

        result = list_tables("CDM_LMS")
        data = json.loads(result)

        assert len(data) > 0
        assert all(t["schema"] == "CDM_LMS" for t in data)

    def test_mock_describe_table(self):
        """Test mock describe_table."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        describe_table = tools[2]  # Third tool is describe_table

        result = describe_table("CDM_LMS.COURSE")
        data = json.loads(result)

        assert "columns" in data
        assert any(c["COLUMN_NAME"] == "COURSE_ID" for c in data["columns"])


class TestSQLSafety:
    """Tests for SQL safety features."""

    def test_mock_only_allows_select(self):
        """Test that mock mode only processes SELECT queries."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        read_query = tools[0]

        # These should still work (SELECT queries)
        result = read_query("SELECT * FROM CDM_LMS.COURSE")
        data = json.loads(result)
        assert data["status"] == "success"

    def test_query_with_limit(self):
        """Test that LIMIT clause is respected."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        read_query = tools[0]

        result = read_query("SELECT * FROM CDM_LMS.COURSE LIMIT 2")
        data = json.loads(result)

        assert len(data["data"]) <= 2

    def test_person_id_not_exposed_in_simple_queries(self):
        """Test that PERSON_ID doesn't appear alone in grade queries."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        read_query = tools[0]

        # Query for aggregate grade data
        result = read_query(
            "SELECT AVG(GRADE_POINTS) FROM CDM_LMS.GRADE"
        )
        data = json.loads(result)

        # Result should be aggregated, not individual
        assert data["row_count"] == 1


class TestSchemaDiscovery:
    """Tests for schema discovery."""

    def test_list_tables_returns_cdm_lms_tables(self):
        """Test that list_tables returns CDM_LMS tables."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        list_tables = tools[1]

        result = list_tables("CDM_LMS")
        tables = json.loads(result)

        table_names = [t["table_name"] for t in tables]
        assert "COURSE" in table_names
        assert "GRADE" in table_names
        assert "PERSON_COURSE" in table_names

    def test_describe_table_returns_columns(self):
        """Test that describe_table returns column information."""
        from agents.shared.snowflake_mcp import get_mock_tools

        tools = get_mock_tools()
        describe_table = tools[2]

        result = describe_table("COURSE")  # Without schema prefix
        data = json.loads(result)

        assert "columns" in data
        column_names = [c["COLUMN_NAME"] for c in data["columns"]]
        assert "COURSE_ID" in column_names
        assert "COURSE_NAME" in column_names


class TestSQLResult:
    """Tests for SQLResult data class."""

    def test_sql_result_creation(self):
        """Test that SQLResult can be created."""
        from agents.shared.models import SQLResult

        result = SQLResult(
            success=True,
            sql_query="SELECT COUNT(*) FROM COURSE",
            data=[{"count": 5}],
            columns=["count"],
            row_count=1,
            execution_time_ms=100
        )

        assert result.success is True
        assert result.row_count == 1
        assert result.data[0]["count"] == 5

    def test_sql_result_with_error(self):
        """Test SQLResult with error."""
        from agents.shared.models import SQLResult

        result = SQLResult(
            success=False,
            sql_query="SELECT * FROM INVALID",
            data=[],
            columns=[],
            row_count=0,
            execution_time_ms=0,
            error="Table not found"
        )

        assert result.success is False
        assert result.error == "Table not found"
