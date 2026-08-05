"""Canonical plan hashing for confirmation binding."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from backend.app.commands.models import (
    AmbiguousPlannedItem,
    InvalidPlannedItem,
    LookupFailedPlannedItem,
    NoOpPlannedItem,
    NotFoundPlannedItem,
    PlannedItemResult,
    ReadyPlannedItem,
)


def compute_plan_hash(
    *,
    plan_id: UUID,
    revision: int,
    user_id: str,
    items: list[PlannedItemResult],
) -> str:
    """Hash canonical non-secret plan data for confirmation binding."""
    payload = {
        "plan_id": str(plan_id),
        "revision": revision,
        "user_id": user_id,
        "items": [_item_hash_payload(item) for item in items],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _item_hash_payload(item: PlannedItemResult) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": str(item.kind),
        "apply_order": item.apply_order,
        "requested": item.requested.model_dump(mode="json"),
        "source_titles": list(item.source_titles),
    }
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        base.update(
            {
                "mal_id": item.media.mal_id,
                "media_type": item.media.media_type.value,
                "before": item.before.model_dump(mode="json"),
                "after": item.after.model_dump(mode="json"),
                "warnings": [w.model_dump(mode="json") for w in item.warnings],
                "is_noop": item.is_noop,
            }
        )
    elif isinstance(item, AmbiguousPlannedItem):
        base.update(
            {
                "query": item.query,
                "reason": item.reason,
                "candidates": [c.model_dump(mode="json") for c in item.candidates],
            }
        )
    elif isinstance(item, NotFoundPlannedItem):
        base.update(
            {
                "query": item.query,
                "media_type": item.media_type.value if item.media_type else None,
                "reason": item.reason,
            }
        )
    elif isinstance(item, InvalidPlannedItem):
        base.update(
            {
                "error_code": item.error_code,
                "error_message": item.error_message,
                "mal_id": item.media.mal_id if item.media else None,
            }
        )
    elif isinstance(item, LookupFailedPlannedItem):
        base.update(
            {
                "error_code": item.error_code,
                "error_message": item.error_message,
                "mal_id": item.media.mal_id if item.media else None,
            }
        )
    return base
