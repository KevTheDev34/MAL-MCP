"""MAL OAuth orchestration service."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from backend.app.auth.errors import (
    MalNotConnectedError,
    MalReconnectRequiredError,
    OAuthConfigurationError,
    OAuthProviderDeniedError,
    OAuthStateExpiredError,
    OAuthStateInvalidError,
    OAuthTokenExchangeError,
)
from backend.app.auth.mal_oauth import MalOAuthHttpClient
from backend.app.auth.pkce import generate_code_verifier, generate_oauth_state
from backend.app.auth.schemas import (
    MalConnectedResponse,
    MalConnectionStatus,
    MalDisconnectResponse,
)
from backend.app.auth.token_store import TokenStore
from backend.app.config import Settings
from backend.app.db.repositories.oauth_credentials import OAuthCredentialRepository
from backend.app.db.repositories.oauth_states import OAuthStateRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.services.clock import Clock
from backend.app.services.encryption import EncryptionError, EncryptionService

logger = logging.getLogger(__name__)


class MalOAuthService:
    """Coordinate MAL OAuth connect, disconnect, status, and token refresh."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        encryption: EncryptionService,
        clock: Clock,
        http_client: MalOAuthHttpClient | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock
        self._users = UserRepository(session)
        self._states = OAuthStateRepository(session)
        self._token_store = TokenStore(OAuthCredentialRepository(session), encryption)
        self._http = http_client or MalOAuthHttpClient(settings)
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _ensure_oauth_configured(self) -> None:
        try:
            self._settings.require_mal_oauth_settings()
        except ValueError as exc:
            raise OAuthConfigurationError(str(exc)) from exc

    def begin_authorization(self) -> str:
        """Create OAuth state and return the MAL authorize redirect URL."""
        self._ensure_oauth_configured()
        user = self._users.get_or_create_local_user()
        now = self._clock.now()
        self._states.delete_expired(now)

        state = generate_oauth_state()
        code_verifier = generate_code_verifier()
        expires_at = now + timedelta(
            minutes=self._settings.oauth_state_expiration_minutes
        )
        self._states.create(
            state=state,
            code_verifier=code_verifier,
            user_id=user.id,
            expires_at=expires_at,
        )
        self._session.commit()
        logger.info("Started MAL OAuth flow for local user")
        return self._http.build_authorize_url(state=state, code_verifier=code_verifier)

    async def complete_authorization(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> MalConnectedResponse:
        """Validate callback, exchange code, store encrypted tokens and identity."""
        self._ensure_oauth_configured()

        if error:
            logger.info("MAL OAuth provider denied authorization error=%s", error)
            _ = error_description  # intentionally unused; may contain sensitive detail
            raise OAuthProviderDeniedError("MAL authorization was denied")

        if not code or not state:
            raise OAuthStateInvalidError("Missing authorization code or state")

        row = self._states.get_by_state(state)
        if row is None:
            raise OAuthStateInvalidError("Unknown OAuth state")
        if row.consumed_at is not None:
            raise OAuthStateInvalidError("OAuth state has already been used")

        now = self._clock.now()
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now.tzinfo)
        if expires_at <= now:
            raise OAuthStateExpiredError("OAuth state has expired")

        code_verifier = row.code_verifier
        user_id = row.user_id
        self._states.consume(row, consumed_at=now)
        self._session.commit()

        tokens = await self._http.exchange_authorization_code(
            code=code,
            code_verifier=code_verifier,
        )
        mal_user = await self._http.get_current_user(tokens.access_token)
        token_expires_at = now + timedelta(seconds=tokens.expires_in)

        self._token_store.save_tokens(
            user_id=user_id,
            provider_user_id=str(mal_user.id),
            provider_username=mal_user.name,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=token_expires_at,
            last_refresh_at=None,
        )
        self._session.commit()
        logger.info(
            "MAL OAuth connected provider_user_id=%s",
            mal_user.id,
        )
        return MalConnectedResponse(
            connected=True,
            mal_user_id=str(mal_user.id),
            mal_username=mal_user.name,
            token_expires_at=token_expires_at,
        )

    def get_status(self) -> MalConnectionStatus:
        """Return public connection status for the local user."""
        user = self._users.get_or_create_local_user()
        credential = self._token_store.get_credential(user.id)
        if credential is None:
            self._session.commit()
            return MalConnectionStatus(connected=False)

        has_refresh = bool(credential.encrypted_refresh_token)
        reconnect_required = not has_refresh
        self._session.commit()
        return MalConnectionStatus(
            connected=has_refresh,
            mal_user_id=credential.provider_user_id,
            mal_username=credential.provider_username,
            token_expires_at=credential.expires_at if has_refresh else None,
            reconnect_required=reconnect_required,
        )

    def disconnect(self) -> MalDisconnectResponse:
        """Remove stored MAL credentials for the local user."""
        user = self._users.get_or_create_local_user()
        self._token_store.delete_for_user(user.id)
        self._states.delete_for_user(user.id)
        self._session.commit()
        logger.info("MAL OAuth disconnected for local user")
        return MalDisconnectResponse(connected=False)

    async def get_valid_access_token(self) -> str:
        """Return a valid access token, refreshing when near expiry."""
        self._ensure_oauth_configured()
        user = self._users.get_or_create_local_user()
        credential = self._token_store.get_credential(user.id)
        if credential is None:
            raise MalNotConnectedError("MAL is not connected")

        tokens = self._token_store.decrypt_tokens(credential)
        if tokens is None:
            raise MalReconnectRequiredError("MAL reconnect is required")

        now = self._clock.now()
        skew = timedelta(seconds=self._settings.token_refresh_skew_seconds)
        expires_at = credential.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now.tzinfo)

        if expires_at is not None and expires_at > now + skew:
            return tokens.access_token

        try:
            refreshed = await self._http.refresh_access_token(tokens.refresh_token)
        except (OAuthTokenExchangeError, EncryptionError) as exc:
            logger.warning("MAL token refresh failed: %s", type(exc).__name__)
            self._token_store.clear_tokens(credential)
            self._session.commit()
            raise MalReconnectRequiredError("MAL reconnect is required") from exc

        new_expires = now + timedelta(seconds=refreshed.expires_in)
        self._token_store.save_tokens(
            user_id=user.id,
            provider_user_id=credential.provider_user_id,
            provider_username=credential.provider_username,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token,
            expires_at=new_expires,
            last_refresh_at=now,
        )
        self._session.commit()
        logger.info("MAL access token refreshed")
        return refreshed.access_token
