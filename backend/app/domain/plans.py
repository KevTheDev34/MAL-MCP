"""Planned changes and change plans (Phase 6 contract shapes)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.enums import CommandState, DomainErrorCode, PlanWarningCode
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.state import CurrentListState, ProposedListState


class PlanWarning(BaseModel):
    """Typed warning attached to a planned change."""

    model_config = ConfigDict(extra="forbid")

    code: PlanWarningCode
    message: str
    field: str | None = None


class PlannedChange(BaseModel):
    """One proposed future MAL list change after resolution."""

    model_config = ConfigDict(extra="forbid")

    change_id: UUID
    media: ResolvedMedia
    before: CurrentListState
    after: ProposedListState
    warnings: list[PlanWarning] = Field(default_factory=list)
    is_noop: bool = False
    requires_confirmation: bool = True

    @model_validator(mode="after")
    def _validate_media_type_alignment(self) -> PlannedChange:
        if (
            self.before.media_type != self.media.media_type
            or self.after.media_type != self.media.media_type
        ):
            raise DomainValidationError(
                "Planned change before/after media_type must match resolved media",
                code=DomainErrorCode.MEDIA_TYPE_MISMATCH,
            )
        return self


class ChangePlan(BaseModel):
    """Collection of planned changes for one user command.

    ``plan_hash`` and ``expires_at`` remain optional until Phase 6/7.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    revision: int = Field(ge=1)
    user_id: str
    state: CommandState
    original_text: str | None = None
    changes: list[PlannedChange] = Field(default_factory=list)
    plan_hash: str | None = None
    expires_at: datetime | None = None
    created_at: datetime

    @field_validator("user_id")
    @classmethod
    def _user_id_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise DomainValidationError(
                "user_id must not be empty",
                code=DomainErrorCode.EMPTY_USER_ID,
                field="user_id",
            )
        return stripped

    @field_validator("created_at", "expires_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise DomainValidationError(
                "Datetimes must be timezone-aware",
                code=DomainErrorCode.TIMEZONE_REQUIRED,
            )
        return value

    @model_validator(mode="after")
    def _validate_unique_change_ids(self) -> ChangePlan:
        seen: set[UUID] = set()
        for change in self.changes:
            if change.change_id in seen:
                raise DomainValidationError(
                    f"Duplicate change_id in plan: {change.change_id}",
                    code=DomainErrorCode.DUPLICATE_CHANGE_ID,
                    field="changes",
                )
            seen.add(change.change_id)
        return self
