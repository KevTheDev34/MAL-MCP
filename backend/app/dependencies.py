"""FastAPI dependency providers."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.app.db.session import get_db as _get_db


def get_db_session() -> Generator[Session, None, None]:
    """Provide a database session to route handlers."""
    yield from _get_db()
