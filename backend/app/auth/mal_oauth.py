"""MAL OAuth HTTP helpers (authorize, token exchange, identity)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import ValidationError

from backend.app.auth.errors import (
    OAuthIdentityError,
    OAuthTokenExchangeError,
    OAuthTokenTemporaryError,
)
from backend.app.auth.pkce import plain_code_challenge
from backend.app.auth.schemas import MalTokenResponse, MalUser
from backend.app.config import Settings

logger = logging.getLogger(__name__)

_DEFINITIVE_TOKEN_FAILURE_STATUSES = frozenset({400, 401, 403})
_TEMPORARY_TOKEN_FAILURE_STATUSES = frozenset({429, 500, 502, 503, 504})


class MalOAuthHttpClient:
    """Minimal HTTP client for MAL OAuth token and identity endpoints."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    def build_authorize_url(self, *, state: str, code_verifier: str) -> str:
        """Build the MAL authorization redirect URL."""
        params = {
            "response_type": "code",
            "client_id": self._settings.mal_client_id,
            "state": state,
            "redirect_uri": self._settings.mal_redirect_uri,
            "code_challenge": plain_code_challenge(code_verifier),
            "code_challenge_method": "plain",
        }
        return f"{self._settings.mal_authorize_url}?{urlencode(params)}"

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> MalTokenResponse:
        """Exchange an authorization code for access and refresh tokens."""
        data = {
            "client_id": self._settings.mal_client_id,
            "client_secret": self._settings.mal_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.mal_redirect_uri,
            "code_verifier": code_verifier,
        }
        return await self._request_tokens(data)

    async def refresh_access_token(self, refresh_token: str) -> MalTokenResponse:
        """Refresh access and refresh tokens."""
        data = {
            "client_id": self._settings.mal_client_id,
            "client_secret": self._settings.mal_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return await self._request_tokens(data)

    async def get_current_user(self, access_token: str) -> MalUser:
        """Fetch the authenticated MAL user identity."""
        url = f"{self._settings.mal_api_base_url.rstrip('/')}/users/@me"
        try:
            response = await self._http.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            logger.warning("MAL identity request failed: %s", type(exc).__name__)
            raise OAuthIdentityError("Failed to reach MAL identity endpoint") from exc

        if response.status_code != 200:
            logger.warning(
                "MAL identity request returned status=%s",
                response.status_code,
            )
            raise OAuthIdentityError("MAL identity endpoint returned an error")

        try:
            payload: dict[str, Any] = response.json()
            return MalUser.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            logger.warning("MAL identity payload was invalid")
            raise OAuthIdentityError("MAL identity response was invalid") from exc

    async def _request_tokens(self, data: dict[str, str]) -> MalTokenResponse:
        try:
            response = await self._http.post(
                self._settings.mal_token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            logger.warning("MAL token request failed: %s", type(exc).__name__)
            raise OAuthTokenTemporaryError(
                "Failed to reach MAL token endpoint"
            ) from exc

        if response.status_code != 200:
            logger.warning(
                "MAL token request returned status=%s",
                response.status_code,
            )
            if response.status_code in _TEMPORARY_TOKEN_FAILURE_STATUSES:
                raise OAuthTokenTemporaryError(
                    "MAL token endpoint returned a temporary error"
                )
            if response.status_code in _DEFINITIVE_TOKEN_FAILURE_STATUSES:
                raise OAuthTokenExchangeError("MAL token endpoint returned an error")
            # Unexpected statuses are treated as definitive so callers do not
            # silently keep a potentially invalid refresh token forever.
            raise OAuthTokenExchangeError("MAL token endpoint returned an error")

        try:
            payload: dict[str, Any] = response.json()
            return MalTokenResponse.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            logger.warning("MAL token payload was invalid")
            raise OAuthTokenExchangeError("MAL token response was invalid") from exc
