"""Deterministic title resolution for MyAnimeList media."""

from backend.app.resolver.aliases import AliasService
from backend.app.resolver.errors import (
    ResolverAliasStoreError,
    ResolverAuthenticationError,
    ResolverEnrichmentError,
    ResolverError,
    ResolverTemporaryError,
    ResolverValidationError,
)
from backend.app.resolver.hints import extract_title_hints
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolutionCandidate,
    ResolutionOutcome,
    ResolvedOutcome,
    ResolveTitleRequest,
    TitleHints,
    resolution_outcome_adapter,
)
from backend.app.resolver.normalize import (
    normalize_for_comparison,
    normalize_for_search,
)
from backend.app.resolver.policy import DEFAULT_RESOLVER_POLICY, ResolverPolicy
from backend.app.resolver.service import TitleResolver

__all__ = [
    "AliasService",
    "AmbiguousOutcome",
    "DEFAULT_RESOLVER_POLICY",
    "NotFoundOutcome",
    "ResolutionCandidate",
    "ResolutionOutcome",
    "ResolvedOutcome",
    "ResolveTitleRequest",
    "ResolverAliasStoreError",
    "ResolverAuthenticationError",
    "ResolverEnrichmentError",
    "ResolverError",
    "ResolverPolicy",
    "ResolverTemporaryError",
    "ResolverValidationError",
    "TitleHints",
    "TitleResolver",
    "extract_title_hints",
    "normalize_for_comparison",
    "normalize_for_search",
    "resolution_outcome_adapter",
]
