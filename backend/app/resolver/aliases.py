"""Alias lookup and persistence for title resolution."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.models import TitleAlias
from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.domain.enums import MediaType
from backend.app.resolver.errors import ResolverAliasStoreError
from backend.app.resolver.normalize import normalize_for_comparison
from backend.app.services.clock import Clock


@dataclass(frozen=True)
class AliasMatch:
    """Validated alias target ready to seed as a resolution candidate."""

    alias: TitleAlias
    media_type: MediaType
    mal_id: int
    canonical_title: str


class AliasService:
    """User-specific title alias operations."""

    def __init__(
        self,
        *,
        repository: TitleAliasRepository,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def lookup(
        self,
        *,
        user_id: str,
        title: str,
        media_type: MediaType | None = None,
    ) -> list[AliasMatch]:
        """Return stored aliases for the normalized title."""
        normalized = normalize_for_comparison(title)
        if not normalized:
            return []
        try:
            rows = self._repository.get(
                user_id=user_id,
                alias_normalized=normalized,
                media_type=media_type,
            )
        except SQLAlchemyError as exc:
            raise ResolverAliasStoreError("Alias lookup failed") from exc

        matches: list[AliasMatch] = []
        for row in rows:
            try:
                mt = MediaType(row.media_type)
            except ValueError:
                continue
            matches.append(
                AliasMatch(
                    alias=row,
                    media_type=mt,
                    mal_id=row.mal_id,
                    canonical_title=row.canonical_title,
                )
            )
        return matches

    def save(
        self,
        *,
        user_id: str,
        alias: str,
        media_type: MediaType,
        mal_id: int,
        canonical_title: str,
    ) -> TitleAlias:
        """Create or update an alias after explicit user clarification."""
        normalized = normalize_for_comparison(alias)
        if not normalized:
            raise ResolverAliasStoreError("Alias text must not be empty")
        try:
            return self._repository.upsert(
                user_id=user_id,
                alias_normalized=normalized,
                media_type=media_type,
                mal_id=mal_id,
                canonical_title=canonical_title.strip(),
                now=self._clock.now(),
            )
        except SQLAlchemyError as exc:
            raise ResolverAliasStoreError("Alias save failed") from exc

    def touch(self, alias: TitleAlias) -> None:
        """Update last-used timestamp after successful alias-assisted resolve."""
        try:
            self._repository.touch(alias, now=self._clock.now())
        except SQLAlchemyError as exc:
            raise ResolverAliasStoreError("Alias touch failed") from exc
