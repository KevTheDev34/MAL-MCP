"""OAuth state repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.db.models import OAuthState


class OAuthStateRepository:
    """Persistence helpers for single-use OAuth states."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        state: str,
        code_verifier: str,
        user_id: str,
        expires_at: datetime,
    ) -> OAuthState:
        row = OAuthState(
            state=state,
            code_verifier=code_verifier,
            user_id=user_id,
            expires_at=expires_at,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_by_state(self, state: str) -> OAuthState | None:
        return self._session.scalar(select(OAuthState).where(OAuthState.state == state))

    def consume(self, row: OAuthState, consumed_at: datetime) -> None:
        row.consumed_at = consumed_at
        self._session.flush()

    def delete_for_user(self, user_id: str) -> None:
        self._session.execute(delete(OAuthState).where(OAuthState.user_id == user_id))
        self._session.flush()

    def delete_expired(self, now: datetime) -> None:
        self._session.execute(delete(OAuthState).where(OAuthState.expires_at <= now))
        self._session.flush()
