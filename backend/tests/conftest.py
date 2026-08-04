"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import Settings, get_settings
from backend.app.db.base import Base
from backend.app.dependencies import get_clock, get_db_session
from backend.app.main import create_app
from backend.app.services.clock import FixedClock
from backend.app.services.encryption import EncryptionService


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def oauth_settings(fernet_key: str) -> Settings:
    return Settings(
        app_env="test",
        app_secret_key="test-secret",
        database_url="sqlite://",
        mal_client_id="test-client-id",
        mal_client_secret="test-client-secret",
        mal_redirect_uri="http://testserver/auth/mal/callback",
        token_encryption_key=fernet_key,
        request_timeout_seconds=5,
        oauth_state_expiration_minutes=10,
        token_refresh_skew_seconds=60,
    )


@pytest.fixture
def encryption_service(fernet_key: str) -> EncryptionService:
    return EncryptionService(fernet_key)


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock(datetime(2026, 8, 4, 15, 0, 0, tzinfo=UTC))


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session with schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> Generator[TestClient, None, None]:
    """HTTP test client with DB, settings, and clock overrides."""
    get_settings.cache_clear()
    application = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def override_settings() -> Settings:
        return oauth_settings

    def override_clock() -> FixedClock:
        return fixed_clock

    application.dependency_overrides[get_db_session] = override_get_db
    application.dependency_overrides[get_settings] = override_settings
    application.dependency_overrides[get_clock] = override_clock

    with TestClient(application) as test_client:
        yield test_client

    application.dependency_overrides.clear()
    get_settings.cache_clear()
