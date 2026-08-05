"""Read-after-write verification for applied MAL list changes."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.domain.enums import MediaType
from backend.app.domain.state import CurrentListState, ProposedListState


@dataclass
class VerificationResult:
    """Outcome of comparing intended proposed state to remote state."""

    kind: str
    verified_state: CurrentListState | None = None
    field_mismatches: list[str] = field(default_factory=list)
    message: str | None = None


def verify_proposed_against_remote(
    *,
    intended: ProposedListState,
    remote: CurrentListState | None,
    media_type: MediaType,
) -> VerificationResult:
    """Compare intended proposed fields against a normalized remote read."""
    if remote is None:
        return VerificationResult(
            kind="item_missing",
            message="List entry missing after write",
        )
    if remote.media_type != media_type:
        return VerificationResult(
            kind="unexpected_remote_state",
            verified_state=remote,
            message="Remote media type did not match intended media type",
        )
    if not remote.is_on_list:
        return VerificationResult(
            kind="item_missing",
            verified_state=remote,
            message="Entry is not on the list after write",
        )

    mismatches: list[str] = []
    if intended.status is not None and remote.status != intended.status:
        mismatches.append("status")
    if intended.score is not None and remote.score != intended.score:
        mismatches.append("score")
    if media_type is MediaType.ANIME:
        if (
            intended.episode_progress is not None
            and remote.episode_progress != intended.episode_progress
        ):
            mismatches.append("episode_progress")
    else:
        if (
            intended.chapter_progress is not None
            and remote.chapter_progress != intended.chapter_progress
        ):
            mismatches.append("chapter_progress")
        if (
            intended.volume_progress is not None
            and remote.volume_progress != intended.volume_progress
        ):
            mismatches.append("volume_progress")

    if mismatches:
        return VerificationResult(
            kind="mismatch",
            verified_state=remote,
            field_mismatches=mismatches,
            message="Read-after-write verification mismatched intended fields",
        )
    return VerificationResult(kind="verified", verified_state=remote)


def states_equal_for_stale_check(
    stored_before: CurrentListState,
    observed: CurrentListState,
) -> bool:
    """Full domain current-state equality for stale-plan detection."""
    return stored_before.model_dump(mode="json") == observed.model_dump(mode="json")
