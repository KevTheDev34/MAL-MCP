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
    OAuthTokenTemporaryError,
)
from backend.app.commands.errors import (
    AttemptAlreadyInProgressError,
    AttemptOutcomeUnknownError,
    CommandError,
    HistoryNotFoundError,
    IdempotencyConflictError,
    PlanAlreadyAppliedError,
    PlanCanceledError,
    PlanConcurrencyError,
    PlanExpiredError,
    PlanHashMismatchError,
    PlanNotApplyableError,
    PlanNotConfirmableError,
    PlanNotFoundError,
    PlanOwnershipError,
    PlanResolveFailedError,
    PlanRevisionMismatchError,
    PlanValidationError,
    RecoveryNotRequiredError,
    UndoAlreadyCompletedError,
    UndoConflictError,
    UndoError,
    UndoInProgressError,
    UndoNotEligibleError,
    UndoSourceNotVerifiedError,
    UndoTargetMissingError,
)
from backend.app.config import get_settings
from backend.app.logging_config import configure_logging
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalError,
    MalRateLimitError,
    MalTemporaryError,
    MalValidationError,
)
from backend.app.resolver.errors import (
    ResolverAuthenticationError,
    ResolverError,
    ResolverTemporaryError,
    ResolverValidationError,
)

logger = logging.getLogger(__name__)

_AUTH_STATUS: dict[type[AuthError], int] = {
    OAuthConfigurationError: 503,
    OAuthStateInvalidError: 400,
    OAuthStateExpiredError: 400,
    OAuthProviderDeniedError: 400,
    OAuthTokenExchangeError: 502,
    OAuthTokenTemporaryError: 502,
    OAuthIdentityError: 502,
    MalNotConnectedError: 404,
    MalReconnectRequiredError: 401,
}

_COMMAND_STATUS: dict[type[CommandError], int] = {
    PlanNotFoundError: 404,
    PlanOwnershipError: 403,
    PlanExpiredError: 410,
    PlanRevisionMismatchError: 409,
    PlanHashMismatchError: 409,
    PlanNotConfirmableError: 409,
    PlanNotApplyableError: 409,
    PlanAlreadyAppliedError: 409,
    PlanCanceledError: 409,
    PlanConcurrencyError: 409,
    PlanValidationError: 400,
    PlanResolveFailedError: 502,
    HistoryNotFoundError: 404,
    IdempotencyConflictError: 409,
    AttemptAlreadyInProgressError: 409,
    AttemptOutcomeUnknownError: 409,
    RecoveryNotRequiredError: 409,
    UndoNotEligibleError: 409,
    UndoAlreadyCompletedError: 409,
    UndoConflictError: 409,
    UndoSourceNotVerifiedError: 409,
    UndoTargetMissingError: 404,
    UndoInProgressError: 409,
    UndoError: 409,
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

    @application.exception_handler(CommandError)
    async def command_error_handler(
        _request: Request,
        exc: CommandError,
    ) -> JSONResponse:
        status_code = _COMMAND_STATUS.get(type(exc), 400)
        logger.info(
            "Command error type=%s status=%s",
            exc.error_code,
            status_code,
        )
        payload: dict[str, str] = {
            "error": exc.error_code,
            "message": exc.message,
        }
        if isinstance(exc, PlanValidationError):
            payload["error"] = exc.code
            if exc.field:
                payload["field"] = exc.field
        if isinstance(exc, PlanResolveFailedError):
            payload["error"] = exc.code
        return JSONResponse(status_code=status_code, content=payload)

    @application.exception_handler(MalError)
    async def mal_error_handler(
        _request: Request,
        exc: MalError,
    ) -> JSONResponse:
        status_code = 502
        if isinstance(exc, MalAuthenticationError):
            status_code = 401
        elif isinstance(exc, MalValidationError):
            status_code = 400
        elif isinstance(exc, MalRateLimitError | MalTemporaryError):
            status_code = 503
        logger.info("MAL error type=%s status=%s", exc.error_code, status_code)
        return JSONResponse(
            status_code=status_code,
            content={"error": exc.error_code, "message": exc.message},
        )

    @application.exception_handler(ResolverError)
    async def resolver_error_handler(
        _request: Request,
        exc: ResolverError,
    ) -> JSONResponse:
        status_code = 502
        if isinstance(exc, ResolverAuthenticationError):
            status_code = 401
        elif isinstance(exc, ResolverValidationError):
            status_code = 400
        elif isinstance(exc, ResolverTemporaryError):
            status_code = 503
        logger.info(
            "Resolver error type=%s status=%s",
            exc.error_code,
            status_code,
        )
        return JSONResponse(
            status_code=status_code,
            content={"error": exc.error_code, "message": exc.message},
        )


app = create_app()
