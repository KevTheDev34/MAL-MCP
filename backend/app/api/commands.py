"""Command plan/confirm/apply API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from backend.app.commands.models import (
    ApplyPlanRequest,
    ApplyPlanResponse,
    ChangePlanView,
    ConfirmPlanRequest,
    ConfirmPlanResponse,
    CreateChangePlanRequest,
    HistoryCommandDetail,
    RecoveryResult,
    UndoPlanResponse,
)
from backend.app.commands.service import CommandApplicationService
from backend.app.db.models import User
from backend.app.dependencies import get_command_service, get_local_user

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post("/plan", response_model=ChangePlanView)
async def create_plan(
    body: CreateChangePlanRequest,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> ChangePlanView:
    return await service.create_plan(user_id=user.id, request=body)


@router.get("/{plan_id}", response_model=ChangePlanView)
def get_plan(
    plan_id: UUID,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> ChangePlanView:
    return service.get_plan(user_id=user.id, plan_id=plan_id)


@router.get("/{plan_id}/history", response_model=HistoryCommandDetail)
def get_plan_history(
    plan_id: UUID,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> HistoryCommandDetail:
    return service.get_plan_history(user_id=user.id, plan_id=plan_id)


@router.post("/{plan_id}/confirm", response_model=ConfirmPlanResponse)
def confirm_plan(
    plan_id: UUID,
    body: ConfirmPlanRequest,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> ConfirmPlanResponse:
    return service.confirm(
        user_id=user.id,
        plan_id=plan_id,
        revision=body.revision,
        plan_hash=body.plan_hash,
    )


@router.post("/{plan_id}/apply", response_model=ApplyPlanResponse)
async def apply_plan(
    plan_id: UUID,
    body: ApplyPlanRequest,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> ApplyPlanResponse:
    return await service.apply(
        user_id=user.id,
        plan_id=plan_id,
        revision=body.revision,
    )


@router.post("/{plan_id}/recover", response_model=RecoveryResult)
async def recover_plan(
    plan_id: UUID,
    body: ApplyPlanRequest,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> RecoveryResult:
    return await service.recover(
        user_id=user.id,
        plan_id=plan_id,
        revision=body.revision,
    )


@router.post("/{plan_id}/items/{item_id}/undo-plan", response_model=UndoPlanResponse)
async def create_item_undo_plan(
    plan_id: UUID,
    item_id: UUID,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> UndoPlanResponse:
    return await service.create_undo_plan_for_item(
        user_id=user.id,
        plan_id=plan_id,
        item_id=item_id,
    )


@router.post("/{plan_id}/cancel", response_model=ChangePlanView)
def cancel_plan(
    plan_id: UUID,
    user: Annotated[User, Depends(get_local_user)],
    service: Annotated[CommandApplicationService, Depends(get_command_service)],
) -> ChangePlanView:
    return service.cancel(user_id=user.id, plan_id=plan_id)
