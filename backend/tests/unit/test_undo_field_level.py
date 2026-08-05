"""Unit tests for field-level undo helpers."""

from __future__ import annotations

from backend.app.commands.undo import (
    build_field_level_restore,
    changed_fields,
    same_field_conflicts,
)
from backend.app.domain.enums import AnimeStatus, MediaType
from backend.app.domain.state import CurrentListState, ProposedListState


def _before(**kwargs: object) -> CurrentListState:
    base = {
        "media_type": MediaType.ANIME,
        "is_on_list": True,
        "status": AnimeStatus.WATCHING,
        "score": 7,
        "episode_progress": 10,
    }
    base.update(kwargs)
    return CurrentListState.model_validate(base)


def _after(**kwargs: object) -> ProposedListState:
    base = {
        "media_type": MediaType.ANIME,
        "status": AnimeStatus.WATCHING,
        "score": 8,
        "episode_progress": 10,
    }
    base.update(kwargs)
    return ProposedListState.model_validate(base)


def test_changed_fields_detects_score_only() -> None:
    assert changed_fields(_before(), _after()) == ["score"]


def test_unrelated_progress_change_does_not_conflict() -> None:
    after = _after()
    current = _before(score=8, episode_progress=11)
    conflicts = same_field_conflicts(after, current, ["score"])
    assert conflicts == []
    restore = build_field_level_restore(
        current=current,
        original_before=_before(),
        changed=["score"],
    )
    assert restore.score == 7
    assert restore.episode_progress == 11


def test_same_field_external_change_conflicts() -> None:
    after = _after()
    current = _before(score=9, episode_progress=10)
    conflicts = same_field_conflicts(after, current, ["score"])
    assert conflicts == ["score"]
