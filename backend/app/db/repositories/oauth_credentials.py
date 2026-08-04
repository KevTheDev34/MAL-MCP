"""OAuth credential repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import OAuthCredential

MAL_PROVIDER = "mal"


class OAuthCredentialRepository:
    """Persistence helpers for encrypted OAuth credentials."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_user(
        self,
        user_id: str,
        provider: str = MAL_PROVIDER,
    ) -> OAuthCredential | None:
        return self._session.scalar(
            select(OAuthCredential).where(
                OAuthCredential.user_id == user_id,
                OAuthCredential.provider == provider,
            )
        )

    def upsert_mal_credentials(
        self,
        *,
        user_id: str,
        provider_user_id: str,
        provider_username: str,
        encrypted_access_token: str,
        encrypted_refresh_token: str,
        expires_at: datetime,
        last_refresh_at: datetime | None = None,
    ) -> OAuthCredential:
        existing = self.get_for_user(user_id)
        if existing is None:
            existing = OAuthCredential(
                user_id=user_id,
                provider=MAL_PROVIDER,
                provider_user_id=provider_user_id,
                provider_username=provider_username,
                encrypted_access_token=encrypted_access_token,
                encrypted_refresh_token=encrypted_refresh_token,
                expires_at=expires_at,
                last_refresh_at=last_refresh_at,
            )
            self._session.add(existing)
        else:
            existing.provider_user_id = provider_user_id
            existing.provider_username = provider_username
            existing.encrypted_access_token = encrypted_access_token
            existing.encrypted_refresh_token = encrypted_refresh_token
            existing.expires_at = expires_at
            existing.last_refresh_at = last_refresh_at
        self._session.flush()
        return existing

    def clear_tokens(self, credential: OAuthCredential) -> None:
        credential.encrypted_access_token = None
        credential.encrypted_refresh_token = None
        credential.expires_at = None
        self._session.flush()

    def delete_for_user(self, user_id: str, provider: str = MAL_PROVIDER) -> bool:
        existing = self.get_for_user(user_id, provider)
        if existing is None:
            return False
        self._session.delete(existing)
        self._session.flush()
        return True
