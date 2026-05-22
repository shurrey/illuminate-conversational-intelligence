"""Offline tests for the semantic layer: load + compile + dispatch validation.

These tests do not touch Snowflake or Bedrock. They verify that the canonical
YAML loads, every metric compiles to a Snowflake-safe SELECT, and the tool's
input validation rejects bad inputs before any execution path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from semantic_layer.engine import (
    ALLOWED_TABLES,
    SqlSafetyError,
    compile_sql,
    load_canonical,
    merge,
    resolve,
)
from semantic_layer.tool import (
    TOOL_SPEC,
    format_catalog_for_prompt,
    query_metric_catalog,
)

DUMMY_DATABASE = "ILLUMINATE_TEST"


# ---------------------------------------------------------------------------
# Canonical YAML loads
# ---------------------------------------------------------------------------


def test_canonical_catalog_loads_eighteen_metrics():
    cat = load_canonical()
    assert len(cat.metrics) == 18
    expected_ids = {
        # Chat-shaped metrics (derived from verified_queries.json)
        "metric.student_count.v1",
        "metric.instructor_count.v1",
        "metric.course_count.v1",
        "metric.active_courses.by_term.v1",
        "metric.enrollment_count.by_term.v1",
        "metric.enrollment_count.by_course.v1",
        "metric.enrollment_summary.v1",
        "metric.average_gpa.v1",
        "metric.average_gpa.by_term.v1",
        "metric.average_gpa.for_term.v1",
        "metric.grade_distribution.v1",
        "metric.course_completion_rate.v1",
        # Dashboard-shaped metrics (current vs previous window comparisons)
        "metric.dashboard.active_students.v1",
        "metric.dashboard.retention_rate.v1",
        "metric.dashboard.platform_engagement.v1",
        "metric.dashboard.active_courses.v1",
        "metric.dashboard.instructor_engagement.v1",
        "metric.dashboard.classic_holdouts.v1",
    }
    assert set(cat.metrics.keys()) == expected_ids


def test_dashboard_metrics_compile_with_ctes():
    """Dashboard metric SQL uses CTEs heavily. sqlglot exposes CTE references
    as Table nodes; the engine must exclude CTE-defined names from the
    allowed-tables check or every dashboard metric fails safety validation."""
    cat = load_canonical()
    dashboard_ids = [mid for mid in cat.metrics if mid.startswith("metric.dashboard.")]
    assert len(dashboard_ids) == 6
    for mid in dashboard_ids:
        merged = resolve(cat, None, mid)
        sql = compile_sql(merged, filters=[], dimensions=[], database=DUMMY_DATABASE)
        # All dashboard metrics return a single row with current/previous/diff
        # columns. The SQL is a WITH ... SELECT structure.
        upper = sql.strip().upper()
        assert upper.startswith("WITH"), f"{mid} not a CTE query"


def test_every_metric_owner_is_blackboard():
    cat = load_canonical()
    owners = {m.owner for m in cat.metrics.values()}
    assert owners == {"Blackboard"}


def test_every_metric_synonym_routes_via_glossary():
    """Drift check: each metric's `synonyms` list must be reachable via the
    canonical glossary. If they diverge, the planner sees inconsistent state.
    """
    cat = load_canonical()
    for mid, m in cat.metrics.items():
        for phrase in m.synonyms:
            assert cat.glossary.synonyms.get(phrase) == mid, (
                f"metric {mid} declares synonym {phrase!r} but glossary "
                f"maps it to {cat.glossary.synonyms.get(phrase)!r}"
            )


# ---------------------------------------------------------------------------
# SQL compile + safety
# ---------------------------------------------------------------------------


def test_all_metrics_compile_to_safe_snowflake_select():
    """Every canonical metric must render via Jinja, parse as a SELECT/CTE,
    reference only CDM_LMS allowed tables, and end up with a LIMIT clause.

    Chat-shaped metrics template the database name via `{{ database }}`;
    dashboard-shaped metrics rely on the Snowflake connection's default
    database (no prefix), so the substitution check is conditional.
    """
    cat = load_canonical()
    for mid, m in cat.metrics.items():
        merged = resolve(cat, None, mid)
        sql = compile_sql(merged, filters=[], dimensions=[], database=DUMMY_DATABASE)
        upper = sql.strip().upper()
        assert upper.startswith("WITH") or upper.startswith("SELECT"), (
            f"{mid} did not produce a SELECT/CTE statement"
        )
        assert "LIMIT" in upper, f"{mid} missing LIMIT"
        # Only chat metrics substitute the database name; dashboard metrics
        # use the connection's default. Distinguish by checking whether the
        # template references `{{ database }}`.
        if "{{ database }}" in m.measure_sql or "{{database}}" in m.measure_sql:
            assert DUMMY_DATABASE in sql, (
                f"{mid} templates {{ database }} but didn't substitute"
            )


def test_allowed_tables_covers_all_canonical_references():
    """Sanity check the ALLOWED_TABLES list against what metric SQL actually
    uses. Helps catch the case where a new metric references CDM_SIS or
    CDM_ALY tables and we forget to widen the allowlist."""
    cat = load_canonical()
    for mid, m in cat.metrics.items():
        merged = resolve(cat, None, mid)
        # If compile_sql succeeds, the tables are allowed. The test above
        # asserts compile, so this is mostly a doc-check.
        sql = compile_sql(merged, filters=[], dimensions=[], database=DUMMY_DATABASE)
        # No assertions beyond no-exception — already covered above.
        assert sql


def test_compile_rejects_non_select():
    cat = load_canonical()
    m = cat.metrics["metric.student_count.v1"]
    bad = m.model_copy(update={"measure_sql": "DELETE FROM PERSON"})
    with pytest.raises(SqlSafetyError):
        compile_sql(bad, filters=[], dimensions=[], database=DUMMY_DATABASE)


def test_compile_rejects_unknown_table():
    cat = load_canonical()
    m = cat.metrics["metric.student_count.v1"]
    bad = m.model_copy(update={"measure_sql": "SELECT * FROM SECRET_INTERNAL_TABLE"})
    with pytest.raises(SqlSafetyError):
        compile_sql(bad, filters=[], dimensions=[], database=DUMMY_DATABASE)


# ---------------------------------------------------------------------------
# Tool dispatch — input validation
# ---------------------------------------------------------------------------


def _stub_snowflake(return_value: dict):
    """Patch the lazy-imported snowflake_client module with a Mock whose
    `validate_and_execute` returns `return_value`. The non-None replacement
    short-circuits the lazy-import logic in `query_metric_catalog`."""
    fake = MagicMock()
    fake.validate_and_execute.return_value = return_value
    return patch("semantic_layer.tool.snowflake_client", fake)


def test_tool_rejects_missing_metric_id():
    result = query_metric_catalog({}, database=DUMMY_DATABASE)
    assert "error" in result
    assert "metric_id" in result["error"].lower()


def test_tool_rejects_unknown_metric_id():
    result = query_metric_catalog(
        {"metric_id": "metric.nope.v1"}, database=DUMMY_DATABASE
    )
    assert "error" in result
    assert "unknown metric_id" in result["error"]
    assert "available_metrics" in result
    assert "metric.student_count.v1" in result["available_metrics"]


def test_tool_rejects_invalid_filter_id():
    # student_count has no filters defined
    result = query_metric_catalog(
        {"metric_id": "metric.student_count.v1", "filters": ["nope"]},
        database=DUMMY_DATABASE,
    )
    assert "error" in result
    assert "nope" in result.get("bad_filters", [])


def test_tool_happy_path_with_stubbed_snowflake():
    fake_rows = [{"STUDENT_COUNT": 5000}]
    stub_response = {"columns": ["STUDENT_COUNT"], "rows": fake_rows}
    with _stub_snowflake(stub_response):
        result = query_metric_catalog(
            {"metric_id": "metric.student_count.v1"}, database=DUMMY_DATABASE
        )
    assert "error" not in result, result
    assert result["row_count"] == 1
    assert result["rows"] == fake_rows
    assert result["metric_used"]["id"] == "metric.student_count.v1"
    assert result["metric_used"]["owner"] == "Blackboard"
    assert result["metric_used"]["applied_definition"] == "canonical"
    # SQL substituted the database name and ends with LIMIT
    assert DUMMY_DATABASE in result["sql_executed"]
    assert "LIMIT" in result["sql_executed"].upper()


def test_tool_surfaces_snowflake_error():
    with _stub_snowflake({"error": "permission denied on schema CDM_LMS"}):
        result = query_metric_catalog(
            {"metric_id": "metric.student_count.v1"}, database=DUMMY_DATABASE
        )
    assert "error" in result
    assert "permission denied" in result["error"]
    assert "sql_attempted" in result


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


def test_format_catalog_for_prompt_includes_every_metric():
    summary = format_catalog_for_prompt()
    cat = load_canonical()
    for mid in cat.metrics.keys():
        assert mid in summary, f"prompt summary missing metric id {mid}"


def test_tool_spec_has_required_bedrock_fields():
    assert TOOL_SPEC["name"] == "query_metric_catalog"
    schema = TOOL_SPEC["inputSchema"]["json"]
    assert "metric_id" in schema["properties"]
    assert "metric_id" in schema["required"]
    assert ALLOWED_TABLES  # imported successfully
