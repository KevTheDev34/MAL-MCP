"""API and service models for the Phase 6 command workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.enums import (
    ApplyResultKind,
    CommandState,
    MediaType,
    PlannedItemOutcomeKind,
    PlanWarningCode,
)
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.plans import PlanWarning
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.resolver.models import ResolutionCandidate


class CreateChangePlanRequest(BaseModel):
    """Structured plan creation request (no user identity fields)."""

    model_config = ConfigDict(extra="forbid")

    original_text: str | None = None
    changes: list[RequestedChange]

    @model_validator(mode="after")
    def _require_changes(self) -> CreateChangePlanRequest:
        if not self.changes:
            raise ValueError("At least one requested change is required")
        return self


class ConfirmPlanRequest(BaseModel):
    """Bind confirmation to an exact stored plan revision."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    plan_hash: str


class ApplyPlanRequest(BaseModel):
    """Apply a previously confirmed plan revision."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)


class PlannedItemBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    apply_order: int
    requested: RequestedChange
    source_titles: list[str] = Field(default_factory=list)


class ReadyPlannedItem(PlannedItemBase):
    kind: Literal[PlannedItemOutcomeKind.READY] = PlannedItemOutcomeKind.READY
    media: ResolvedMedia
    before: CurrentListState
    after: ProposedListState
    warnings: list[PlanWarning] = Field(default_factory=list)
    is_noop: Literal[False] = False


class NoOpPlannedItem(PlannedItemBase):
    kind: Literal[PlannedItemOutcomeKind.NOOP] = PlannedItemOutcomeKind.NOOP
    media: ResolvedMedia
    before: CurrentListState
    after: ProposedListState
    warnings: list[PlanWarning] = Field(default_factory=list)
    is_noop: Literal[True] = True


class AmbiguousPlannedItem(PlannedItemBase):
    kind: Literal[PlannedItemOutcomeKind.AMBIGUOUS] = PlannedItemOutcomeKind.AMBIGUOUS
    query: str
    candidates: list[ResolutionCandidate]
    reason: str


class NotFoundPlannedItem(PlannedItemBase):
    kind: Literal[PlannedItemOutcomeKind.NOT_FOUND] = PlannedItemOutcomeKind.NOT_FOUND
    query: str
    media_type: MediaType | None = None
    reason: str


class InvalidPlannedItem(PlannedItemBase):
    kind: Literal[PlannedItemOutcomeKind.INVALID] = PlannedItemOutcomeKind.INVALID
    error_code: str
    error_message: str
    media: ResolvedMedia | None = None
    before: CurrentListState | None = None


class LookupFailedPlannedItem(PlannedItemBase):
    kind: Literal[PlannedItemOutcomeKind.LOOKUP_FAILED] = (
        PlannedItemOutcomeKind.LOOKUP_FAILED
    )
    media: ResolvedMedia | None = None
    error_code: str
    error_message: str


PlannedItemResult = Annotated[
    ReadyPlannedItem
    | NoOpPlannedItem
    | AmbiguousPlannedItem
    | NotFoundPlannedItem
    | InvalidPlannedItem
    | LookupFailedPlannedItem,
    Field(discriminator="kind"),
]


class AppliedItemResult(BaseModel):
    """Per-item apply outcome."""

    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    apply_order: int
    result: ApplyResultKind
    mal_id: int | None = None
    media_type: MediaType | None = None
    canonical_title: str | None = None
    verified_state: CurrentListState | None = None
    observed_state: CurrentListState | None = None
    error_code: str | None = None
    error_message: str | None = None
    field_mismatches: list[str] = Field(default_factory=list)


class ChangePlanView(BaseModel):
    """Stable plan response contract."""

    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    revision: int
    state: CommandState
    original_text: str | None = None
    expires_at: datetime
    confirmed_at: datetime | None = None
    plan_hash: str
    confirmation_required: bool
    confirmable: bool
    applyable: bool
    items: list[PlannedItemResult]
    apply_results: list[AppliedItemResult] = Field(default_factory=list)
    created_at: datetime

    @field_validator("expires_at", "confirmed_at", "created_at")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Datetimes must be timezone-aware")
        return value


class ConfirmPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    revision: int
    state: CommandState
    confirmed_at: datetime
    applyable: bool
    plan_hash: str


class ApplyPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    revision: int
    state: CommandState
    already_applied: bool = False
    requires_new_plan: bool = False
    results: list[AppliedItemResult]
    counts: dict[str, int] = Field(default_factory=dict)


def warning(
    code: PlanWarningCode,
    message: str,
    *,
    field: str | None = None,
) -> PlanWarning:
    return PlanWarning(code=code, message=message, field=field)


def dump_json_obj(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
