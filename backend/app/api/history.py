"""History and undo API routes (Phase 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.app.commands.models import (
    CreateUndoPlanRequest,
    HistoryCommandDetail,
    HistoryListResponse,
    UndoPlanResponse,
)
from backend.app.commands.service import CommandApplicationService
from backend.app.db.models import User
from backend.app.dependencies import get_command_service, get_local_user
from backend.app.domain.enums import MediaType

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=HistoryListResponse)
def list_history(
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    state: str | None = None,
    is_undo: bool | None = None,
    media_type: MediaType | None = None,
    mal_id: int | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> HistoryListResponse:
    return service.list_history(
        user_id=user.id,
        limit=limit,
        offset=offset,
        state=state,
        is_undo=is_undo,
        media_type=media_type,
        mal_id=mal_id,
        created_after=created_after,
        created_before=created_before,
    )


@router.get("/{command_id}", response_model=HistoryCommandDetail)
def get_command_history(
    command_id: UUID,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> HistoryCommandDetail:
    return service.get_command_history(user_id=user.id, command_id=command_id)


@router.post("/{command_id}/undo-plan", response_model=UndoPlanResponse)
async def create_undo_plan(
    command_id: UUID,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
    body: CreateUndoPlanRequest | None = None,
) -> UndoPlanResponse:
    return await service.create_undo_plan(
        user_id=user.id,
        command_id=command_id,
        request=body or CreateUndoPlanRequest(),
    )
