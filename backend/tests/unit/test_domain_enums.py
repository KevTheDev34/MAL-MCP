"""Unit tests for domain enumerations."""

from __future__ import annotations

from backend.app.domain.enums import (
    AnimeStatus,
    CommandState,
    MangaStatus,
    MediaType,
)


def test_media_type_values() -> None:
    assert MediaType.ANIME == "anime"
    assert MediaType.MANGA == "manga"
    assert set(MediaType) == {MediaType.ANIME, MediaType.MANGA}


def test_anime_status_values() -> None:
    assert {status.value for status in AnimeStatus} == {
        "watching",
        "completed",
        "on_hold",
        "dropped",
        "plan_to_watch",
    }


def test_manga_status_values() -> None:
    assert {status.value for status in MangaStatus} == {
        "reading",
        "completed",
        "on_hold",
        "dropped",
        "plan_to_read",
    }


def test_command_state_stable_serialization() -> None:
    assert CommandState.AWAITING_CONFIRMATION.value == "awaiting_confirmation"
    assert CommandState.PARTIALLY_APPLIED == "partially_applied"
    dumped = [state.value for state in CommandState]
    assert dumped == [
        "received",
        "parsed",
        "resolving",
        "awaiting_clarification",
        "planned",
        "awaiting_confirmation",
        "applying",
        "verified",
        "rejected",
        "failed",
        "partially_applied",
        "reverted",
    ]
