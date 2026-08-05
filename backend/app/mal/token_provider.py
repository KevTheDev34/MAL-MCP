"""Protocol for obtaining a valid MAL access token."""

from __future__ import annotations

from typing import Protocol


class MalAccessTokenProvider(Protocol):
    """Supplies bearer tokens for authenticated MAL API calls."""

    async def get_valid_access_token(self, *, force_refresh: bool = False) -> str:
        """Return a usable access token, refreshing when needed or forced."""
        ...
