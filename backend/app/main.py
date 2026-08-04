"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api.router import api_router
from backend.app.auth.errors import (
    AuthError,
    MalNotConnectedError,
    MalReconnectRequiredError,
    OAuthConfigurationError,
    OAuthIdentityError,
    OAuthProviderDeniedError,
    OAuthStateExpiredError,
    OAuthStateInvalidError,
    OAuthTokenExchangeError,
)
from backend.app.config import get_settings
from backend.app.logging_config import configure_logging

logger = logging.getLogger(__name__)

_AUTH_STATUS: dict[type[AuthError], int] = {
    OAuthConfigurationError: 503,
    OAuthStateInvalidError: 400,
    OAuthStateExpiredError: 400,
    OAuthProviderDeniedError: 400,
    OAuthTokenExchangeError: 502,
    OAuthIdentityError: 502,
    MalNotConnectedError: 404,
    MalReconnectRequiredError: 401,
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Application starting env=%s", settings.app_env)
    yield
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    application = FastAPI(
        title="MAL Conversational Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(api_router)
    _register_exception_handlers(application)
    return application


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AuthError)
    async def auth_error_handler(
        _request: Request,
        exc: AuthError,
    ) -> JSONResponse:
        status_code = _AUTH_STATUS.get(type(exc), 400)
        logger.info(
            "Auth error type=%s status=%s",
            exc.error_code,
            status_code,
        )
        return JSONResponse(
            status_code=status_code,
            content={"error": exc.error_code, "message": exc.message},
        )


app = create_app()
