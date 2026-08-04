"""Unit tests for TokenStore."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.auth.token_store import DecryptedTokens, TokenStore
from backend.app.db.repositories.oauth_credentials import OAuthCredentialRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.services.encryption import EncryptionService
from backend.tests.fixtures.mal_oauth_responses import (
    FIXTURE_ACCESS_TOKEN,
    FIXTURE_REFRESH_TOKEN,
)


def test_tokens_encrypted_at_rest(
    db_session: Session,
    encryption_service: EncryptionService,
) -> None:
    user = UserRepository(db_session).get_or_create_local_user()
    store = TokenStore(OAuthCredentialRepository(db_session), encryption_service)
    store.save_tokens(
        user_id=user.id,
        provider_user_id="123",
        provider_username="alice",
        access_token=FIXTURE_ACCESS_TOKEN,
        refresh_token=FIXTURE_REFRESH_TOKEN,
        expires_at=datetime(2026, 8, 4, 16, 0, tzinfo=UTC),
    )
    db_session.commit()

    credential = store.get_credential(user.id)
    assert credential is not None
    assert credential.encrypted_access_token is not None
    assert credential.encrypted_access_token != FIXTURE_ACCESS_TOKEN
    assert credential.encrypted_refresh_token != FIXTURE_REFRESH_TOKEN

    decrypted = store.decrypt_tokens(credential)
    assert decrypted is not None
    assert decrypted.access_token == FIXTURE_ACCESS_TOKEN
    assert decrypted.refresh_token == FIXTURE_REFRESH_TOKEN


def test_decrypted_tokens_repr_redacts() -> None:
    tokens = DecryptedTokens(
        access_token=FIXTURE_ACCESS_TOKEN,
        refresh_token=FIXTURE_REFRESH_TOKEN,
    )
    rendered = repr(tokens)
    assert FIXTURE_ACCESS_TOKEN not in rendered
    assert FIXTURE_REFRESH_TOKEN not in rendered
    assert "***REDACTED***" in rendered
