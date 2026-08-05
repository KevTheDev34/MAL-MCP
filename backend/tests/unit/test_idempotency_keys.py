"""Unit tests for apply idempotency keys and field clears."""

from __future__ import annotations

from uuid import uuid4

from backend.app.commands.idempotency import build_apply_idempotency_key
from backend.app.domain.enums import AnimeStatus, MediaType
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.mal.domain_mapping import proposed_anime_state_to_update


def test_idempotency_key_is_deterministic() -> None:
    plan_id = uuid4()
    item_id = uuid4()
    a = build_apply_idempotency_key(
        user_id="user-1",
        plan_id=plan_id,
        revision=1,
        planned_item_id=item_id,
        plan_hash="abc",
    )
    b = build_apply_idempotency_key(
        user_id="user-1",
        plan_id=plan_id,
        revision=1,
        planned_item_id=item_id,
        plan_hash="abc",
    )
    assert a == b
    assert a.startswith("apply:user-1:")


def test_proposed_anime_clear_score_and_progress() -> None:
    before = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        score=8,
        episode_progress=10,
    )
    after = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.WATCHING,
        score=None,
        episode_progress=None,
    )
    update = proposed_anime_state_to_update(before=before, after=after)
    assert update.score == 0
    assert update.num_watched_episodes == 0
