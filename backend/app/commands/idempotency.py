"""Server-side apply idempotency key helpers."""

from __future__ import annotations

from uuid import UUID


def build_apply_idempotency_key(
    *,
    user_id: str,
    plan_id: UUID | str,
    revision: int,
    planned_item_id: UUID | str,
    plan_hash: str,
) -> str:
    """Build a deterministic per-item apply idempotency key.

    Format: apply:{user_id}:{plan_id}:{revision}:{item_id}:{plan_hash}
    """
    return (
        f"apply:{user_id}:{plan_id}:{revision}:{planned_item_id}:{plan_hash}"
    )


def legacy_idempotency_key(attempt_id: str) -> str:
    """Fallback key for pre-Phase-7 attempt rows that cannot be reconstructed."""
    return f"legacy:{attempt_id}"
