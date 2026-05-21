"""The `query_metric_catalog` tool implementation for the Bedrock Converse loop.

The outer agent in chat_engine.py sees the canonical metric catalog in its
system prompt (see `format_catalog_for_prompt`). When the user's question
matches a metric, the agent calls this tool with a `metric_id`; the tool
resolves the merged definition (canonical + any tenant overlay — none in MVP),
compiles SQL, executes it against Snowflake, and returns aggregated rows
plus provenance.

This is option 1 from the Step 2 design: the outer model acts as the
planner. A separate Bedrock planner call would be option 2 — easy to add
later by wrapping this function.
"""

from __future__ import annotations

import logging
from typing import Any

# snowflake_client is lazy-imported inside `query_metric_catalog` so tests
# (which don't have boto3 / AWS credentials) can import this module freely
# and stub the Snowflake call via `semantic_layer.tool.snowflake_client`.
snowflake_client = None  # type: ignore[assignment]

from .engine import SqlSafetyError, compile_sql, load_canonical, resolve

logger = logging.getLogger("API-PROXY")


def query_metric_catalog(input: dict[str, Any], database: str) -> dict[str, Any]:
    """Run a canonical metric and return JSON-serializable result.

    Args:
        input: Tool input from Bedrock Converse. Required field: `metric_id`.
            Optional: `filters` (list of filter ids), `dimensions` (list of
            dimension ids). All ids must exist on the resolved merged metric.
        database: Snowflake database name, injected into the metric's
            Jinja-templated SQL as `{{ database }}`.
    """
    metric_id = input.get("metric_id", "").strip()
    if not metric_id:
        return {
            "error": "metric_id is required",
            "hint": "Pick a metric id from the Canonical Metric Catalog section of your system prompt.",
        }

    canonical = load_canonical()
    if metric_id not in canonical.metrics:
        return {
            "error": f"unknown metric_id: {metric_id!r}",
            "available_metrics": sorted(canonical.metrics.keys()),
        }

    # No tenant overlays in MVP. When Cognito tenant claim wiring lands,
    # resolve from a tenant_id propagated through the request context.
    tenant = None
    merged = resolve(canonical, tenant, metric_id)

    filter_ids = input.get("filters") or []
    dim_ids = input.get("dimensions") or []

    valid_filters = {f.id for f in merged.effective_filters}
    valid_dimensions = {d.id for d in merged.valid_dimensions}
    bad_filters = [f for f in filter_ids if f not in valid_filters]
    bad_dimensions = [d for d in dim_ids if d not in valid_dimensions]
    if bad_filters or bad_dimensions:
        return {
            "error": "invalid filters or dimensions",
            "bad_filters": bad_filters,
            "bad_dimensions": bad_dimensions,
            "valid_filters": sorted(valid_filters),
            "valid_dimensions": sorted(valid_dimensions),
        }

    filter_objs = [f for f in merged.effective_filters if f.id in filter_ids]
    dimension_objs = [d for d in merged.valid_dimensions if d.id in dim_ids]

    try:
        sql = compile_sql(
            merged,
            filters=filter_objs,
            dimensions=dimension_objs,
            database=database,
        )
    except SqlSafetyError as e:
        return {"error": f"SQL safety violation in metric definition: {e}"}

    logger.info("query_metric_catalog: %s -> %s", metric_id, sql[:200])
    global snowflake_client
    if snowflake_client is None:
        import snowflake_client as _sf  # noqa: F401 — populates module global
        snowflake_client = _sf
    result = snowflake_client.validate_and_execute(sql, None)
    if "error" in result:
        logger.warning("query_metric_catalog snowflake error: %s", result["error"])
        return {
            "error": f"Snowflake execution failed: {result['error']}",
            "sql_attempted": sql,
        }

    rows = result.get("rows", [])
    return {
        "metric_used": {
            "id": merged.id,
            "version": merged.version,
            "display_name": merged.canonical.display_name,
            "description": merged.canonical.description.strip(),
            "applied_definition": merged.applied_definition,
            "owner": merged.overlay.owner if merged.overlay else merged.canonical.owner,
            "overlay_diff": (
                merged.overlay.diff_description if merged.overlay else None
            ),
        },
        "sql_executed": sql,
        "columns": result.get("columns", []),
        "rows": rows,
        "row_count": len(rows),
    }


def format_catalog_for_prompt() -> str:
    """Markdown summary of the canonical catalog, for injection into the
    Bedrock Converse system prompt.

    Each metric block lists id, display name, description, synonyms, and
    example questions — enough for the outer agent to map a user's question
    to the right metric_id without seeing the full SQL.
    """
    cat = load_canonical()
    blocks: list[str] = []
    for m in cat.metrics.values():
        block_lines = [f"### `{m.id}` — {m.display_name}"]
        block_lines.append(m.description.strip())
        if m.synonyms:
            block_lines.append(f"  Synonyms: {', '.join(m.synonyms)}")
        if m.example_questions:
            block_lines.append(
                f"  Examples: " + "; ".join(f'"{q}"' for q in m.example_questions)
            )
        blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


# Bedrock Converse toolSpec for use in `toolConfig.tools`.
TOOL_SPEC = {
    "name": "query_metric_catalog",
    "description": (
        "Execute a pre-vetted canonical metric from the Blackboard catalog. "
        "Use this in preference to `execute_sql` when the user's question matches "
        "an entry in the Canonical Metric Catalog section of your system prompt. "
        "Pass the metric's `id` field exactly. Optionally pass `filters` and "
        "`dimensions` (lists of ids declared on the metric). The tool resolves "
        "the canonical definition (plus any tenant overlay), compiles "
        "Snowflake SQL, executes it, and returns aggregated rows along with "
        "provenance (which metric was used, owner, definition description). If "
        "the metric_id is invalid, the tool returns an error listing available "
        "metric ids — you can retry with a corrected id, or fall back to "
        "`execute_sql` if no metric fits."
    ),
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "metric_id": {
                    "type": "string",
                    "description": (
                        "Exact canonical metric id, e.g. "
                        "`metric.average_gpa.by_term.v1`. Must match an entry "
                        "in the Canonical Metric Catalog."
                    ),
                },
                "filters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Filter ids declared on the metric's `default_filters` "
                        "(or `extra_filters` if a tenant overlay applies). "
                        "Empty for most current metrics."
                    ),
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Dimension ids declared on the metric's "
                        "`valid_dimensions`. Empty for most current metrics."
                    ),
                },
            },
            "required": ["metric_id"],
        }
    },
}


__all__ = ["TOOL_SPEC", "format_catalog_for_prompt", "query_metric_catalog"]
