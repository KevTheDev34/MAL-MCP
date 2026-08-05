"""Dependency injection providers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.app.auth.errors import OAuthConfigurationError
from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings, get_settings
from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.db.session import get_db as _get_db
from backend.app.mal.client import MalClient
from backend.app.resolver.aliases import AliasService
from backend.app.resolver.policy import ResolverPolicy
from backend.app.resolver.service import TitleResolver
from backend.app.services.clock import Clock, SystemClock
from backend.app.services.encryption import EncryptionError, EncryptionService


def get_db_session() -> Generator[Session, None, None]:
    """Provide a database session to route handlers."""
    yield from _get_db()


def get_clock() -> Clock:
    """Provide the system clock."""
    return SystemClock()


def get_encryption_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EncryptionService:
    """Provide Fernet encryption; invalid non-empty keys fail closed."""
    try:
        return EncryptionService(settings.token_encryption_key)
    except EncryptionError as exc:
        raise OAuthConfigurationError(str(exc)) from exc


async def get_mal_oauth_service(
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    encryption: Annotated[EncryptionService, Depends(get_encryption_service)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> AsyncIterator[MalOAuthService]:
    """Provide a request-scoped MAL OAuth service."""
    service = MalOAuthService(
        session=db,
        settings=settings,
        encryption=encryption,
        clock=clock,
    )
    try:
        yield service
    finally:
        await service.aclose()


async def get_mal_client(
    settings: Annotated[Settings, Depends(get_settings)],
    oauth: Annotated[MalOAuthService, Depends(get_mal_oauth_service)],
) -> AsyncIterator[MalClient]:
    """Provide a request-scoped authenticated MAL API client."""
    client = MalClient(settings=settings, token_provider=oauth)
    try:
        yield client
    finally:
        await client.aclose()


def get_resolver_policy(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResolverPolicy:
    """Provide resolver limits and confidence thresholds from settings."""
    return ResolverPolicy(
        search_limit=settings.resolver_search_limit,
        max_enrich_candidates=settings.resolver_max_enrich_candidates,
        max_ambiguity_candidates=settings.resolver_max_ambiguity_candidates,
        max_mal_gets=settings.resolver_max_mal_gets,
        resolve_min_confidence=settings.resolver_resolve_min_confidence,
        resolve_min_margin=settings.resolver_resolve_min_margin,
        resolve_min_raw_score=settings.resolver_resolve_min_raw_score,
        plausible_min_raw_score=settings.resolver_plausible_min_raw_score,
    )


def get_title_resolver(
    db: Annotated[Session, Depends(get_db_session)],
    client: Annotated[MalClient, Depends(get_mal_client)],
    clock: Annotated[Clock, Depends(get_clock)],
    policy: Annotated[ResolverPolicy, Depends(get_resolver_policy)],
) -> TitleResolver:
    """Provide a title resolver for scripts and future diagnostic use."""
    alias_service = AliasService(
        repository=TitleAliasRepository(db),
        clock=clock,
    )
    return TitleResolver(
        mal_client=client,
        alias_service=alias_service,
        policy=policy,
    )
