"""Pydantic models for MAL OAuth boundaries."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MalUser(BaseModel):
    """Authenticated MAL account identity from ``/users/@me``."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class MalTokenResponse(BaseModel):
    """Token endpoint response (tokens never leave the auth layer)."""

    model_config = ConfigDict(extra="ignore")

    token_type: str
    expires_in: int
    access_token: str
    refresh_token: str


class MalConnectionStatus(BaseModel):
    """Public MAL connection status (no tokens)."""

    connected: bool
    provider: str = "mal"
    mal_user_id: str | None = None
    mal_username: str | None = None
    token_expires_at: datetime | None = None
    reconnect_required: bool = False


class MalDisconnectResponse(BaseModel):
    """Result of disconnecting MAL."""

    connected: bool = False


class MalConnectedResponse(BaseModel):
    """Successful OAuth callback result (no tokens)."""

    connected: bool = True
    provider: str = "mal"
    mal_user_id: str
    mal_username: str
    token_expires_at: datetime


class ErrorResponse(BaseModel):
    """User-safe API error body."""

    error: str
    message: str = Field(description="Safe message without secrets")
