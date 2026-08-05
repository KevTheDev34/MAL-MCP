"""Persistence helpers for user-specific title aliases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import TitleAlias
from backend.app.domain.enums import MediaType


class TitleAliasRepository:
    """CRUD for ``title_aliases``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(
        self,
        *,
        user_id: str,
        alias_normalized: str,
        media_type: MediaType | None = None,
    ) -> list[TitleAlias]:
        """Return matching aliases for a user.

        When ``media_type`` is set, filter to that type. Otherwise return all
        media-type variants for the normalized alias text.
        """
        stmt = select(TitleAlias).where(
            TitleAlias.user_id == user_id,
            TitleAlias.alias_normalized == alias_normalized,
        )
        if media_type is not None:
            stmt = stmt.where(TitleAlias.media_type == media_type.value)
        return list(self._session.scalars(stmt).all())

    def upsert(
        self,
        *,
        user_id: str,
        alias_normalized: str,
        media_type: MediaType,
        mal_id: int,
        canonical_title: str,
        now: datetime,
    ) -> TitleAlias:
        """Create or update an alias for ``(user, alias, media_type)``."""
        existing = self.get(
            user_id=user_id,
            alias_normalized=alias_normalized,
            media_type=media_type,
        )
        if existing:
            alias = existing[0]
            alias.mal_id = mal_id
            alias.canonical_title = canonical_title
            alias.last_used_at = now
            self._session.flush()
            return alias

        alias = TitleAlias(
            user_id=user_id,
            alias_normalized=alias_normalized,
            media_type=media_type.value,
            mal_id=mal_id,
            canonical_title=canonical_title,
            created_at=now,
            last_used_at=now,
        )
        self._session.add(alias)
        self._session.flush()
        return alias

    def touch(self, alias: TitleAlias, *, now: datetime) -> None:
        """Update ``last_used_at`` after a successful alias-assisted resolve."""
        alias.last_used_at = now
        self._session.flush()
