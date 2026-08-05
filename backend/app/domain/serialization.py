"""Canonical JSON serialization for domain models.

Phase 7 plan hashing will use this helper on a defined plan subset.
Hashing itself is not implemented here.
"""

from __future__ import annotations

import json

from pydantic import BaseModel


def canonical_domain_json(model: BaseModel) -> str:
    """Serialize a domain model to stable, deterministic JSON.

    Uses Pydantic JSON mode (enums as strings, datetimes as ISO-8601),
    sorted object keys, and compact separators suitable for later hashing.
    """
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
