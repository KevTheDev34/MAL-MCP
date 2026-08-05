"""MAL list pagination helpers."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.app.mal.errors import MalUnexpectedResponseError
from backend.app.mal.models import Paging


def parse_paging(payload: dict[str, Any]) -> Paging:
    """Parse MAL ``paging`` object; missing key means no further pages."""
    raw = payload.get("paging")
    if raw is None:
        return Paging()
    if not isinstance(raw, dict):
        raise MalUnexpectedResponseError("MAL paging metadata was malformed")
    try:
        return Paging.model_validate(raw)
    except ValidationError as exc:
        raise MalUnexpectedResponseError(
            "MAL paging metadata was malformed"
        ) from exc


def parse_list_page_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``data`` array from a MAL list/search page."""
    raw = payload.get("data")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MalUnexpectedResponseError("MAL list page data was malformed")
    items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise MalUnexpectedResponseError("MAL list page item was malformed")
        items.append(item)
    return items
