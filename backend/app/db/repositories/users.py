"""User repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import User

LOCAL_DISPLAY_NAME = "local"


class UserRepository:
    """Persistence helpers for local users."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create_local_user(self) -> User:
        """Return the singleton local user, creating it if needed."""
        existing = self._session.scalar(
            select(User).where(User.display_name == LOCAL_DISPLAY_NAME).limit(1)
        )
        if existing is not None:
            return existing

        user = User(display_name=LOCAL_DISPLAY_NAME)
        self._session.add(user)
        self._session.flush()
        return user
