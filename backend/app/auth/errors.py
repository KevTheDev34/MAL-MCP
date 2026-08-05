"""Typed authentication and OAuth errors."""

from __future__ import annotations


class AuthError(Exception):
    """Base class for authentication-layer errors."""

    error_code: str = "auth_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class OAuthConfigurationError(AuthError):
    """Required OAuth settings are missing or invalid."""

    error_code = "oauth_configuration_error"


class OAuthStateInvalidError(AuthError):
    """OAuth state is missing, reused, or mismatched."""

    error_code = "oauth_state_invalid"


class OAuthStateExpiredError(AuthError):
    """OAuth state has expired."""

    error_code = "oauth_state_expired"


class OAuthProviderDeniedError(AuthError):
    """The user or provider denied authorization."""

    error_code = "oauth_provider_denied"


class OAuthTokenExchangeError(AuthError):
    """Token endpoint failed or returned an unexpected payload."""

    error_code = "oauth_token_exchange_error"


class OAuthTokenTemporaryError(AuthError):
    """Token endpoint was unreachable or returned a temporary server error."""

    error_code = "oauth_token_temporary_error"


class OAuthIdentityError(AuthError):
    """Failed to retrieve or parse the MAL user identity."""

    error_code = "oauth_identity_error"


class MalNotConnectedError(AuthError):
    """No MAL credentials are stored for the local user."""

    error_code = "mal_not_connected"


class MalReconnectRequiredError(AuthError):
    """Stored tokens are invalid; the user must reconnect."""

    error_code = "mal_reconnect_required"
