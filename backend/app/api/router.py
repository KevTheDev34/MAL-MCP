"""API router aggregation."""

from fastapi import APIRouter

from backend.app.api import auth, commands, health, history

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(commands.router)
api_router.include_router(history.router)
