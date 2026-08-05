"""Application-domain enumerations.

These values are the shared contract for validation, planning, and later
persistence. They are independent of raw MAL JSON field names.
"""

from __future__ import annotations

from enum import StrEnum


class MediaType(StrEnum):
    """Anime versus manga media kind."""

    ANIME = "anime"
    MANGA = "manga"


class AnimeStatus(StrEnum):
    """User anime list status values supported by the assistant."""

    WATCHING = "watching"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"
    PLAN_TO_WATCH = "plan_to_watch"


class MangaStatus(StrEnum):
    """User manga list status values supported by the assistant."""

    READING = "reading"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"
    PLAN_TO_READ = "plan_to_read"


class CommandState(StrEnum):
    """Lifecycle states for a command / change plan."""

    RECEIVED = "received"
    PARSED = "parsed"
    RESOLVING = "resolving"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    PLANNED = "planned"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPLYING = "applying"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAILED = "failed"
    PARTIALLY_APPLIED = "partially_applied"
    REVERTED = "reverted"


class DomainErrorCode(StrEnum):
    """Stable machine-readable codes for domain validation failures."""

    EMPTY_TITLE = "empty_title"
    NO_MUTABLE_FIELDS = "no_mutable_fields"
    INVALID_SCORE = "invalid_score"
    INVALID_PROGRESS = "invalid_progress"
    MEDIA_STATUS_MISMATCH = "media_status_mismatch"
    ANIME_CHAPTER_PROGRESS = "anime_chapter_progress"
    ANIME_VOLUME_PROGRESS = "anime_volume_progress"
    MANGA_EPISODE_PROGRESS = "manga_episode_progress"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    INVALID_CONFIDENCE = "invalid_confidence"
    INVALID_CURRENT_LIST_STATE = "invalid_current_list_state"
    INVALID_PROPOSED_LIST_STATE = "invalid_proposed_list_state"
    INVALID_MAL_ID = "invalid_mal_id"
    EMPTY_CANONICAL_TITLE = "empty_canonical_title"
    MEDIA_TOTAL_MISMATCH = "media_total_mismatch"
    DUPLICATE_CHANGE_ID = "duplicate_change_id"
    INVALID_REVISION = "invalid_revision"
    INVALID_STATUS = "invalid_status"
    MEDIA_TYPE_MISMATCH = "media_type_mismatch"
    TIMEZONE_REQUIRED = "timezone_required"
    EMPTY_USER_ID = "empty_user_id"


class PlanWarningCode(StrEnum):
    """Typed warning categories emitted when building plans (Phase 6)."""

    SCORE_OVERWRITE = "score_overwrite"
    PROGRESS_OVERWRITE = "progress_overwrite"
    STATUS_OVERWRITE = "status_overwrite"
    ONGOING_COMPLETED = "ongoing_completed"
