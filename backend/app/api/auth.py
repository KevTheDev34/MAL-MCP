"""MAL OAuth HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from backend.app.auth.schemas import (
    MalConnectedResponse,
    MalConnectionStatus,
    MalDisconnectResponse,
)
from backend.app.auth.service import MalOAuthService
from backend.app.dependencies import get_mal_oauth_service

router = APIRouter(prefix="/auth/mal", tags=["auth"])

OAuthService = Annotated[MalOAuthService, Depends(get_mal_oauth_service)]


@router.get("/start")
async def start_mal_oauth(service: OAuthService) -> RedirectResponse:
    """Begin MAL OAuth and redirect the browser to MyAnimeList."""
    authorize_url = service.begin_authorization()
    return RedirectResponse(url=authorize_url, status_code=302)


@router.get("/callback", response_model=MalConnectedResponse)
async def mal_oauth_callback(
    service: OAuthService,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> MalConnectedResponse:
    """Handle the MAL OAuth redirect callback."""
    return await service.complete_authorization(
        code=code,
        state=state,
        error=error,
        error_description=error_description,
    )


@router.get("/status", response_model=MalConnectionStatus)
async def mal_oauth_status(service: OAuthService) -> MalConnectionStatus:
    """Return whether MAL is connected for the local user."""
    return service.get_status()


@router.post("/disconnect", response_model=MalDisconnectResponse)
async def mal_oauth_disconnect(service: OAuthService) -> MalDisconnectResponse:
    """Remove stored MAL credentials for the local user."""
    return service.disconnect()
