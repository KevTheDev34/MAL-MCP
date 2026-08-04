"""Health endpoint integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db_session
from backend.app.logging_config import RedactingFilter
from backend.app.main import create_app


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_database_unavailable() -> None:
    application = create_app()
    mock_session = MagicMock()
    mock_session.execute.side_effect = OperationalError(
        "SELECT 1",
        {},
        Exception("connection failed"),
    )

    def broken_db() -> Generator[Session, None, None]:
        yield mock_session

    application.dependency_overrides[get_db_session] = broken_db
    with TestClient(application) as test_client:
        response = test_client.get("/health")

    application.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


def test_redacting_filter_masks_secrets() -> None:
    import logging

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=super-secret-value api_key=abc123",
        args=(),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert "super-secret-value" not in str(record.msg)
    assert "abc123" not in str(record.msg)
    assert "***REDACTED***" in str(record.msg)
