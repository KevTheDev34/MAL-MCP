"""Injectable clock for deterministic expiry tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Provides the current UTC time."""

    def now(self) -> datetime:
        """Return timezone-aware UTC datetime."""
        ...


class SystemClock:
    """Wall-clock UTC time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Mutable clock for tests."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        self._instant = instant
