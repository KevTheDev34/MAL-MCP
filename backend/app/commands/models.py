"""API and service models for the Phase 6 command workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.enums import (
    ApplyResultKind,
    CommandSourceType,
    CommandState,
    MediaType,
    PlannedItemOutcomeKind,
    PlanWarningCode,
    ReversionLinkState,
    ReversionStatus,
    UndoItemOutcomeKind,
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


class RecoveryItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    classification: str
    apply_result: ApplyResultKind
    wrote_again: bool = False
    observed_state: CurrentListState | None = None
    field_mismatches: list[str] = Field(default_factory=list)
    message: str | None = None


class RecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    revision: int
    state: CommandState
    items: list[RecoveryItemResult]
    next_action: str


class CreateUndoPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[UUID] | None = None
    reason: str | None = None


class UndoItemPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_item_id: UUID
    outcome: UndoItemOutcomeKind
    mal_id: int | None = None
    media_type: MediaType | None = None
    canonical_title: str | None = None
    planned_before: CurrentListState | None = None
    verified_after: CurrentListState | None = None
    undo_check_observed: CurrentListState | None = None
    proposed_restore: ProposedListState | None = None
    changed_fields: list[str] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    reverse_item_id: UUID | None = None


class UndoPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_command_id: UUID
    reverse_command_id: UUID
    reverse_plan: ChangePlanView
    items: list[UndoItemPreview]
    ready_count: int
    conflict_count: int
    skipped_count: int


class AttemptHistoryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: UUID
    attempt_number: int
    state: str
    idempotency_key: str
    outcome_certainty: str
    request: dict[str, Any] | None = None
    update_response: dict[str, Any] | None = None
    verified_state: CurrentListState | None = None
    observed_state: CurrentListState | None = None
    field_mismatches: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ReversionHistoryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reversion_id: UUID
    original_planned_item_id: UUID
    reverse_planned_item_id: UUID
    reverse_command_id: UUID
    state: ReversionLinkState
    fully_restored: bool | None = None
    created_at: datetime
    reverted_at: datetime | None = None


class HistoryItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    apply_order: int
    outcome_kind: PlannedItemOutcomeKind
    apply_result_kind: ApplyResultKind | None = None
    reversion_status: ReversionStatus
    mal_id: int | None = None
    media_type: MediaType | None = None
    canonical_title: str | None = None
    requested: RequestedChange
    planned_before: CurrentListState | None = None
    proposed_after: ProposedListState | None = None
    is_noop: bool = False
    undo_eligible: bool = False
    attempts: list[AttemptHistoryView] = Field(default_factory=list)


class HistoryCommandSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    state: CommandState
    source_type: CommandSourceType
    parent_command_id: UUID | None = None
    is_undo: bool
    original_text: str | None = None
    plan_id: UUID | None = None
    revision: int | None = None
    created_at: datetime
    item_count: int = 0
    verified_count: int = 0


class HistoryCommandDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    state: CommandState
    source_type: CommandSourceType
    parent_command_id: UUID | None = None
    is_undo: bool
    original_text: str | None = None
    normalized_request: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    plan: ChangePlanView | None = None
    items: list[HistoryItemView] = Field(default_factory=list)
    reversions: list[ReversionHistoryView] = Field(default_factory=list)


class HistoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HistoryCommandSummary]
    total: int
    limit: int
    offset: int


def warning(
    code: PlanWarningCode,
    message: str,
    *,
    field: str | None = None,
) -> PlanWarning:
    return PlanWarning(code=code, message=message, field=field)


def dump_json_obj(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
