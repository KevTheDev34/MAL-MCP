"""Application-domain models and validation.

This package represents what the MAL Assistant understands, validates, plans,
and records. It must not import MAL HTTP clients, SQLAlchemy ORM models,
FastAPI routes, or LLM clients.

MAL transport models live in ``backend.app.mal.models``. Conversion between
transport and domain lives in ``backend.app.mal.domain_mapping``.
"""

from backend.app.domain.enums import (
    AnimeStatus,
    CommandState,
    DomainErrorCode,
    MangaStatus,
    MediaType,
    PlanWarningCode,
)
from backend.app.domain.errors import DomainError, DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.plans import ChangePlan, PlannedChange, PlanWarning
from backend.app.domain.requests import RequestedChange
from backend.app.domain.serialization import canonical_domain_json
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.domain.transitions import ALLOWED_TRANSITIONS, validate_transition

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AnimeStatus",
    "ChangePlan",
    "CommandState",
    "CurrentListState",
    "DomainError",
    "DomainErrorCode",
    "DomainValidationError",
    "MangaStatus",
    "MediaType",
    "PlanWarning",
    "PlanWarningCode",
    "PlannedChange",
    "ProposedListState",
    "RequestedChange",
    "ResolvedMedia",
    "canonical_domain_json",
    "validate_transition",
]
