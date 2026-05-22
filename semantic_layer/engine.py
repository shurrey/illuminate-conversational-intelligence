"""Semantic engine: load canonical+overlay, merge, resolve metrics, compile SQL.

Differences from the prototype's engine.py (which targets DuckDB):
- sqlglot dialect is 'snowflake' (not 'duckdb').
- The Jinja template render passes a `database` variable so canonical SQL
  can reference fully-qualified table names like `{{ database }}.CDM_LMS.PERSON`.
- ALLOWED_TABLES is the CDM_LMS table set used by the canonical metrics
  (PERSON, COURSE, TERM, PERSON_COURSE, GRADE). Adjust if new metrics
  reference additional tables.

Knows nothing about Bedrock and does not execute SQL — it returns SQL strings.
"""

from __future__ import annotations

from pathlib import Path

import sqlglot
import sqlglot.expressions as exp
import yaml
from jinja2 import Environment, StrictUndefined

from .models import (
    CanonicalCatalog,
    Dimension,
    Filter,
    Glossary,
    MergedMetric,
    Metric,
    OverlayMetric,
    Tenant,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DIR = _PROJECT_ROOT / "canonical"
TENANTS_DIR = _PROJECT_ROOT / "tenants"
DEFAULT_LIMIT = 10_000

# Tables canonical metric SQL is allowed to reference. Update when new metrics
# reference tables not in this set.
ALLOWED_TABLES = {
    "PERSON",
    "COURSE",
    "TERM",
    "PERSON_COURSE",
    "GRADE",
}


class SqlSafetyError(Exception):
    """Raised when generated SQL would violate the engine's safety rules."""


_jinja = Environment(undefined=StrictUndefined, autoescape=False)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_metrics(path: Path) -> dict[str, Metric]:
    data = yaml.safe_load(path.read_text())
    out: dict[str, Metric] = {}
    for raw in data.get("metrics", []):
        m = Metric(**raw)
        out[m.id] = m
    return out


def _load_glossary(path: Path) -> Glossary:
    if not path.exists():
        return Glossary(synonyms={})
    data = yaml.safe_load(path.read_text()) or {}
    return Glossary(synonyms=data.get("synonyms", {}))


def load_canonical(root: Path = CANONICAL_DIR) -> CanonicalCatalog:
    metrics = _load_metrics(root / "metrics.yaml")
    glossary = _load_glossary(root / "glossary.yaml")
    return CanonicalCatalog(metrics=metrics, glossary=glossary)


def load_tenant(tenant_id: str, root: Path = TENANTS_DIR) -> Tenant:
    tdir = root / tenant_id
    tenant_meta = yaml.safe_load((tdir / "tenant.yaml").read_text())
    overlays_raw = yaml.safe_load((tdir / "overlay.yaml").read_text()) or {"overrides": []}
    overlays: dict[str, OverlayMetric] = {}
    for raw in overlays_raw.get("overrides", []):
        ov = OverlayMetric(**raw)
        overlays[ov.canonical_id] = ov
    glossary = _load_glossary(tdir / "glossary.yaml")
    return Tenant(
        id=tenant_meta["id"],
        display_name=tenant_meta["display_name"],
        overlays=overlays,
        glossary=glossary,
    )


# ---------------------------------------------------------------------------
# Merging / resolution
# ---------------------------------------------------------------------------


def merge(canonical: Metric, overlay: OverlayMetric | None) -> MergedMetric:
    if overlay is None:
        return MergedMetric(
            id=canonical.id,
            version=canonical.version,
            applied_definition="canonical",
            canonical=canonical,
            overlay=None,
            effective_measure_sql=canonical.measure_sql,
            effective_filters=list(canonical.default_filters),
            valid_dimensions=list(canonical.valid_dimensions),
        )
    eff_sql = overlay.measure_sql or canonical.measure_sql
    if overlay.override_default_filters is not None:
        base_filters = list(overlay.override_default_filters)
    else:
        base_filters = list(canonical.default_filters)
    eff_filters = base_filters + list(overlay.extra_filters)
    return MergedMetric(
        id=canonical.id,
        version=canonical.version,
        applied_definition="tenant-override",
        canonical=canonical,
        overlay=overlay,
        effective_measure_sql=eff_sql,
        effective_filters=eff_filters,
        valid_dimensions=list(canonical.valid_dimensions),
    )


def resolve(
    canonical: CanonicalCatalog,
    tenant: Tenant | None,
    metric_id: str,
) -> MergedMetric:
    if metric_id not in canonical.metrics:
        raise KeyError(f"Unknown metric: {metric_id}")
    cm = canonical.metrics[metric_id]
    ov = tenant.overlays.get(metric_id) if tenant else None
    return merge(cm, ov)


# ---------------------------------------------------------------------------
# SQL compilation + safety
# ---------------------------------------------------------------------------


def _validate_select_only(sql: str) -> None:
    try:
        parsed = sqlglot.parse_one(sql, read="snowflake")
    except Exception as e:
        raise SqlSafetyError(f"SQL parse failed: {e}") from e
    if not isinstance(parsed, (exp.Select, exp.With)):
        raise SqlSafetyError(
            f"Only SELECT/CTE queries are allowed; got {type(parsed).__name__}"
        )
    referenced = {t.name.upper() for t in parsed.find_all(exp.Table)}
    bad = referenced - ALLOWED_TABLES
    if bad:
        raise SqlSafetyError(f"Disallowed tables referenced: {sorted(bad)}")


def compile_sql(
    metric: Metric | MergedMetric,
    filters: list[Filter],
    dimensions: list[Dimension],
    database: str,
) -> str:
    """Render the metric's Jinja template and validate the resulting SQL.

    Returns a SQL string with `LIMIT {DEFAULT_LIMIT}` appended when the
    template did not already specify one. Raises SqlSafetyError if the
    rendered SQL is not a single SELECT/CTE referencing only allowed tables.

    Args:
        metric: Canonical Metric or post-merge MergedMetric. The function
            reads `effective_measure_sql` from a MergedMetric, else `measure_sql`.
        filters: Filter objects whose `.sql` fragments are AND-joined into a
            WHERE clause passed as Jinja variable `where`.
        dimensions: Dimension objects (reserved for future engine work).
        database: Snowflake database name, substituted as Jinja variable
            `database` (e.g. {{ database }}.CDM_LMS.PERSON).
    """
    template_src = (
        metric.effective_measure_sql
        if isinstance(metric, MergedMetric)
        else metric.measure_sql
    )
    where_clause = " AND ".join(f"({f.sql})" for f in filters) if filters else ""
    tmpl = _jinja.from_string(template_src)
    rendered = tmpl.render(
        where=where_clause,
        dimensions=dimensions,
        database=database,
    )
    _validate_select_only(rendered)
    if "LIMIT" not in rendered.upper():
        rendered = rendered.rstrip().rstrip(";") + f"\nLIMIT {DEFAULT_LIMIT}"
    else:
        rendered = rendered.rstrip().rstrip(";")
    return rendered


__all__ = [
    "ALLOWED_TABLES",
    "SqlSafetyError",
    "compile_sql",
    "load_canonical",
    "load_tenant",
    "merge",
    "resolve",
]
