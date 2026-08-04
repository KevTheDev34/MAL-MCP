"""Dependency injection providers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.app.auth.errors import OAuthConfigurationError
from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings, get_settings
from backend.app.db.session import get_db as _get_db
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
