"""DynamoDB-backed per-tenant overlay storage.

Wraps the OVERLAY_TABLE DynamoDB table. The semantic_layer engine knows
nothing about DynamoDB — this module is the boundary. It returns
`semantic_layer.models.Tenant` / `OverlayMetric` objects that the engine's
`resolve()` can consume directly.

Schema:
    tenant_id   HASH    (string)
    metric_id   RANGE   (string)
    measure_sql            — override SQL
    diff_description       — plain-English description of the override
    owner                  — institutional owner string
    last_reviewed          — ISO date of last review
    updated_at             — ISO timestamp set on every write
    updated_by             — Cognito sub of the editor
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from semantic_layer.models import Glossary, OverlayMetric, Tenant

logger = logging.getLogger("API-PROXY")

TABLE_NAME = os.environ.get("OVERLAY_TABLE", "")

_table = None


def _get_table():
    """Lazy boto3 resource so import-time cost is zero and tests can stub
    the module-level `_table` global to a Mock before any call."""
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def load_tenant(tenant_id: str) -> Tenant:
    """Return a Tenant with every overlay this tenant has authored.

    Returns an empty Tenant (no overlays) if the tenant has no rows yet.
    Never raises on "not found" — every authenticated user gets a Tenant.
    """
    items = _query_tenant_items(tenant_id)
    overlays: dict[str, OverlayMetric] = {}
    for item in items:
        try:
            ov = _item_to_overlay(item)
            overlays[ov.canonical_id] = ov
        except Exception as e:  # noqa: BLE001
            logger.warning("tenant_store: skipping malformed overlay %r: %s", item, e)
    return Tenant(
        id=tenant_id,
        display_name=tenant_id,
        overlays=overlays,
        # Tenant-local glossary not implemented in DynamoDB schema yet.
        glossary=Glossary(synonyms={}),
    )


def get_overlay(tenant_id: str, metric_id: str) -> OverlayMetric | None:
    resp = _get_table().get_item(
        Key={"tenant_id": tenant_id, "metric_id": metric_id}
    )
    item = resp.get("Item")
    if not item:
        return None
    return _item_to_overlay(item)


def put_overlay(
    *,
    tenant_id: str,
    metric_id: str,
    measure_sql: str,
    diff_description: str,
    owner: str,
    updated_by: str,
    last_reviewed: str | None = None,
) -> OverlayMetric:
    """Upsert an overlay. Returns the newly persisted OverlayMetric."""
    now = datetime.now(timezone.utc).isoformat()
    reviewed = last_reviewed or date.today().isoformat()
    item: dict[str, Any] = {
        "tenant_id": tenant_id,
        "metric_id": metric_id,
        "measure_sql": measure_sql,
        "diff_description": diff_description,
        "owner": owner,
        "last_reviewed": reviewed,
        "updated_at": now,
        "updated_by": updated_by,
    }
    _get_table().put_item(Item=item)
    return _item_to_overlay(item)


def delete_overlay(tenant_id: str, metric_id: str) -> None:
    _get_table().delete_item(
        Key={"tenant_id": tenant_id, "metric_id": metric_id}
    )


def _query_tenant_items(tenant_id: str) -> list[dict]:
    resp = _get_table().query(KeyConditionExpression=Key("tenant_id").eq(tenant_id))
    return resp.get("Items", [])


def _item_to_overlay(item: dict) -> OverlayMetric:
    return OverlayMetric(
        canonical_id=item["metric_id"],
        owner=item.get("owner", "Unknown"),
        last_reviewed=date.fromisoformat(
            item.get("last_reviewed", date.today().isoformat())
        ),
        diff_description=item.get("diff_description", ""),
        measure_sql=item.get("measure_sql"),
    )


__all__ = ["load_tenant", "get_overlay", "put_overlay", "delete_overlay"]
