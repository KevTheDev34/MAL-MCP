"""Dependency injection providers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.app.auth.errors import OAuthConfigurationError
from backend.app.auth.service import MalOAuthService
from backend.app.commands.confirmation import PlanConfirmationService
from backend.app.commands.executor import ChangePlanExecutor
from backend.app.commands.history import HistoryService
from backend.app.commands.planner import ChangePlanner
from backend.app.commands.recovery import ApplicationRecoveryService
from backend.app.commands.service import CommandApplicationService
from backend.app.commands.undo import UndoService
from backend.app.config import Settings, get_settings
from backend.app.db.models import User
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.db.session import get_db as _get_db
from backend.app.domain.enums import CommandSourceType
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


def get_local_user(
    db: Annotated[Session, Depends(get_db_session)],
) -> User:
    """Return the singleton local application user."""
    user = UserRepository(db).get_or_create_local_user()
    db.commit()
    return user


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


def get_command_service(
    db: Annotated[Session, Depends(get_db_session)],
    client: Annotated[MalClient, Depends(get_mal_client)],
    resolver: Annotated[TitleResolver, Depends(get_title_resolver)],
    clock: Annotated[Clock, Depends(get_clock)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CommandApplicationService:
    """Provide the command application service with Phase 7 audit/undo."""
    repository = CommandPlanRepository(db)
    planner = ChangePlanner(
        repository=repository,
        resolver=resolver,
        mal_client=client,
        clock=clock,
        plan_expiration_minutes=settings.plan_expiration_minutes,
        max_plan_changes=settings.max_plan_changes,
    )
    confirmation = PlanConfirmationService(repository=repository, clock=clock)
    undo = UndoService(
        repository=repository,
        mal_client=client,
        clock=clock,
        plan_expiration_minutes=settings.plan_expiration_minutes,
        source_type=CommandSourceType.API,
    )
    executor = ChangePlanExecutor(
        repository=repository,
        mal_client=client,
        clock=clock,
        apply_claim_stale_seconds=settings.apply_claim_stale_seconds,
        undo_service=undo,
    )
    recovery = ApplicationRecoveryService(
        repository=repository,
        mal_client=client,
        clock=clock,
        apply_claim_stale_seconds=settings.apply_claim_stale_seconds,
    )
    history = HistoryService(repository=repository)
    return CommandApplicationService(
        planner=planner,
        confirmation=confirmation,
        executor=executor,
        repository=repository,
        clock=clock,
        recovery=recovery,
        undo=undo,
        history=history,
        source_type=CommandSourceType.API,
    )
