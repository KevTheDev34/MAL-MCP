"""Health check endpoint."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

DbSession = Annotated[Session, Depends(get_db_session)]


class HealthResponse(BaseModel):
    """Application and database health status."""

    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
def health_check(db: DbSession) -> HealthResponse | JSONResponse:
    """Return application health, including database connectivity."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "database": "unavailable"},
        )

    return HealthResponse(status="ok", database="ok")
