"""Encrypted OAuth token persistence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.db.models import OAuthCredential
from backend.app.db.repositories.oauth_credentials import OAuthCredentialRepository
from backend.app.services.encryption import EncryptionService


@dataclass(frozen=True)
class DecryptedTokens:
    """Short-lived plaintext tokens (never log or serialize)."""

    access_token: str
    refresh_token: str

    def __repr__(self) -> str:
        return (
            "DecryptedTokens(access_token=***REDACTED***, "
            "refresh_token=***REDACTED***)"
        )

    def __str__(self) -> str:
        return self.__repr__()


class TokenStore:
    """Load and save OAuth credentials with encryption at rest."""

    def __init__(
        self,
        credentials: OAuthCredentialRepository,
        encryption: EncryptionService,
    ) -> None:
        self._credentials = credentials
        self._encryption = encryption

    def get_credential(self, user_id: str) -> OAuthCredential | None:
        return self._credentials.get_for_user(user_id)

    def save_tokens(
        self,
        *,
        user_id: str,
        provider_user_id: str,
        provider_username: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        last_refresh_at: datetime | None = None,
    ) -> OAuthCredential:
        return self._credentials.upsert_mal_credentials(
            user_id=user_id,
            provider_user_id=provider_user_id,
            provider_username=provider_username,
            encrypted_access_token=self._encryption.encrypt(access_token),
            encrypted_refresh_token=self._encryption.encrypt(refresh_token),
            expires_at=expires_at,
            last_refresh_at=last_refresh_at,
        )

    def decrypt_tokens(self, credential: OAuthCredential) -> DecryptedTokens | None:
        if (
            not credential.encrypted_access_token
            or not credential.encrypted_refresh_token
        ):
            return None
        return DecryptedTokens(
            access_token=self._encryption.decrypt(credential.encrypted_access_token),
            refresh_token=self._encryption.decrypt(credential.encrypted_refresh_token),
        )

    def clear_tokens(self, credential: OAuthCredential) -> None:
        self._credentials.clear_tokens(credential)

    def delete_for_user(self, user_id: str) -> bool:
        return self._credentials.delete_for_user(user_id)
