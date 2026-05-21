"""Type vocabulary for the semantic layer. Pydantic v2.

Mirrors the prototype's models.py with one change: `extra='ignore'` on Metric
so the migration YAML's bookkeeping field `originally:` is silently dropped
rather than raising a validation error.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AppliedDefinition = Literal["canonical", "tenant-override"]


class Dimension(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    id: str
    display_name: str
    sql: str


class Filter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    id: str
    sql: str


class Metric(BaseModel):
    """A canonical metric definition. Immutable."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    id: str
    version: str
    display_name: str
    description: str
    owner: str
    authority: str
    last_reviewed: date
    entity: str
    measure_sql: str
    default_filters: list[Filter] = Field(default_factory=list)
    valid_dimensions: list[Dimension] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    example_questions: list[str] = Field(default_factory=list)


class OverlayMetric(BaseModel):
    """A tenant override that references a canonical metric by ID."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    canonical_id: str
    owner: str
    last_reviewed: date
    diff_description: str
    measure_sql: Optional[str] = None
    extra_filters: list[Filter] = Field(default_factory=list)
    override_default_filters: Optional[list[Filter]] = None


class MergedMetric(BaseModel):
    """The resolved metric used for a tenant request. Records provenance."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    id: str
    version: str
    applied_definition: AppliedDefinition
    canonical: Metric
    overlay: Optional[OverlayMetric] = None
    effective_measure_sql: str
    effective_filters: list[Filter] = Field(default_factory=list)
    valid_dimensions: list[Dimension] = Field(default_factory=list)


class Glossary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    synonyms: dict[str, str]


class CanonicalCatalog(BaseModel):
    metrics: dict[str, Metric]
    glossary: Glossary


class Tenant(BaseModel):
    id: str
    display_name: str
    overlays: dict[str, OverlayMetric]
    glossary: Glossary


class QueryPlan(BaseModel):
    metric_id: str
    filters: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)


class QueryResult(BaseModel):
    narrative: str
    value: Optional[float] = None
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    metric_used: MergedMetric
    sql_executed: str
    data_rows: int
    execution_ms: Optional[float] = None
    tenant_id: str
