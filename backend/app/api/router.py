"""API router aggregation."""

from fastapi import APIRouter

from backend.app.api import health

api_router = APIRouter()
api_router.include_router(health.router)
