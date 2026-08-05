"""Typed Pydantic models for MAL API client boundaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MalUser(BaseModel):
    """Authenticated MAL account identity."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class AlternativeTitles(BaseModel):
    """MAL alternative title block."""

    model_config = ConfigDict(extra="ignore")

    synonyms: list[str] = Field(default_factory=list)
    en: str | None = None
    ja: str | None = None


class Paging(BaseModel):
    """MAL pagination metadata."""

    model_config = ConfigDict(extra="ignore")

    previous: str | None = None
    next: str | None = None


class AnimeSearchResult(BaseModel):
    """Anime search hit with fields needed for later title resolution."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    alternative_titles: AlternativeTitles | None = None
    media_type: str | None = None
    start_date: str | None = None
    num_episodes: int | None = None
    status: str | None = None

    @property
    def release_year(self) -> int | None:
        return _year_from_start_date(self.start_date)

    @property
    def english_title(self) -> str | None:
        return self.alternative_titles.en if self.alternative_titles else None

    @property
    def japanese_title(self) -> str | None:
        return self.alternative_titles.ja if self.alternative_titles else None


class MangaSearchResult(BaseModel):
    """Manga search hit with fields needed for later title resolution."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    alternative_titles: AlternativeTitles | None = None
    media_type: str | None = None
    start_date: str | None = None
    num_chapters: int | None = None
    num_volumes: int | None = None
    status: str | None = None

    @property
    def release_year(self) -> int | None:
        return _year_from_start_date(self.start_date)

    @property
    def english_title(self) -> str | None:
        return self.alternative_titles.en if self.alternative_titles else None

    @property
    def japanese_title(self) -> str | None:
        return self.alternative_titles.ja if self.alternative_titles else None


class AnimeDetails(AnimeSearchResult):
    """Anime details by MAL ID."""


class MangaDetails(MangaSearchResult):
    """Manga details by MAL ID."""


class AnimeListStatus(BaseModel):
    """User anime list status fields from MAL responses."""

    model_config = ConfigDict(extra="ignore")

    status: str
    score: int = 0
    num_episodes_watched: int = 0
    is_rewatching: bool = False
    updated_at: datetime | None = None
    start_date: str | None = None
    finish_date: str | None = None


class MangaListStatus(BaseModel):
    """User manga list status fields from MAL responses."""

    model_config = ConfigDict(extra="ignore")

    status: str
    score: int = 0
    num_chapters_read: int = 0
    num_volumes_read: int = 0
    is_rereading: bool = False
    updated_at: datetime | None = None
    start_date: str | None = None
    finish_date: str | None = None


class AnimeListEntry(BaseModel):
    """Anime list entry identified by exact MAL ID."""

    model_config = ConfigDict(extra="ignore")

    mal_id: int
    title: str | None = None
    alternative_titles: AlternativeTitles | None = None
    media_type: str | None = None
    start_date: str | None = None
    num_episodes: int | None = None
    list_status: AnimeListStatus


class MangaListEntry(BaseModel):
    """Manga list entry identified by exact MAL ID."""

    model_config = ConfigDict(extra="ignore")

    mal_id: int
    title: str | None = None
    alternative_titles: AlternativeTitles | None = None
    media_type: str | None = None
    start_date: str | None = None
    num_chapters: int | None = None
    num_volumes: int | None = None
    list_status: MangaListStatus


class AnimeListUpdate(BaseModel):
    """Allowlisted anime list update fields (MAL form body names).

    Note: request field is ``num_watched_episodes``; response field is
    ``num_episodes_watched``.
    """

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    score: int | None = Field(default=None, ge=0, le=10)
    num_watched_episodes: int | None = Field(default=None, ge=0)
    is_rewatching: bool | None = None
    start_date: date | str | None = None
    finish_date: date | str | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> AnimeListUpdate:
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one update field is required")
        return self

    def to_form_data(self) -> dict[str, str]:
        """Encode non-null fields for ``application/x-www-form-urlencoded``."""
        payload: dict[str, str] = {}
        data = self.model_dump(exclude_none=True)
        for key, value in data.items():
            if isinstance(value, bool):
                payload[key] = "true" if value else "false"
            elif isinstance(value, date):
                payload[key] = value.isoformat()
            else:
                payload[key] = str(value)
        return payload


class MangaListUpdate(BaseModel):
    """Allowlisted manga list update fields."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    score: int | None = Field(default=None, ge=0, le=10)
    num_chapters_read: int | None = Field(default=None, ge=0)
    num_volumes_read: int | None = Field(default=None, ge=0)
    is_rereading: bool | None = None
    start_date: date | str | None = None
    finish_date: date | str | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> MangaListUpdate:
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one update field is required")
        return self

    def to_form_data(self) -> dict[str, str]:
        """Encode non-null fields for ``application/x-www-form-urlencoded``."""
        payload: dict[str, str] = {}
        data = self.model_dump(exclude_none=True)
        for key, value in data.items():
            if isinstance(value, bool):
                payload[key] = "true" if value else "false"
            elif isinstance(value, date):
                payload[key] = value.isoformat()
            else:
                payload[key] = str(value)
        return payload


def anime_list_entry_from_status(
    anime_id: int,
    payload: dict[str, Any],
) -> AnimeListEntry:
    """Build an entry from a ``my_list_status`` response body."""
    return AnimeListEntry(
        mal_id=anime_id,
        list_status=AnimeListStatus.model_validate(payload),
    )


def manga_list_entry_from_status(
    manga_id: int,
    payload: dict[str, Any],
) -> MangaListEntry:
    """Build an entry from a ``my_list_status`` response body."""
    return MangaListEntry(
        mal_id=manga_id,
        list_status=MangaListStatus.model_validate(payload),
    )


def anime_resolution_context_from_payload(
    payload: dict[str, Any],
) -> tuple[AnimeDetails, bool]:
    """Parse anime details and whether the title is on the user's list.

    Unlike ``anime_list_entry_from_details``, details are retained when the
    title is not on the list.
    """
    if "id" not in payload:
        raise ValueError("Anime details missing id")
    list_status = payload.get("my_list_status")
    if list_status is not None and not isinstance(list_status, dict):
        raise ValueError("Anime details my_list_status was malformed")
    details = AnimeDetails.model_validate(payload)
    return details, list_status is not None


def manga_resolution_context_from_payload(
    payload: dict[str, Any],
) -> tuple[MangaDetails, bool]:
    """Parse manga details and whether the title is on the user's list."""
    if "id" not in payload:
        raise ValueError("Manga details missing id")
    list_status = payload.get("my_list_status")
    if list_status is not None and not isinstance(list_status, dict):
        raise ValueError("Manga details my_list_status was malformed")
    details = MangaDetails.model_validate(payload)
    return details, list_status is not None


def anime_list_entry_from_details(payload: dict[str, Any]) -> AnimeListEntry | None:
    """Build an entry from anime details that include ``my_list_status``.

    Returns ``None`` when the media exists but is not on the user's list.
    """
    details, on_list = anime_resolution_context_from_payload(payload)
    if not on_list:
        return None
    list_status = payload.get("my_list_status")
    if not isinstance(list_status, dict):
        raise ValueError("Anime details my_list_status was malformed")
    return AnimeListEntry(
        mal_id=details.id,
        title=details.title,
        alternative_titles=details.alternative_titles,
        media_type=details.media_type,
        start_date=details.start_date,
        num_episodes=details.num_episodes,
        list_status=AnimeListStatus.model_validate(list_status),
    )


def manga_list_entry_from_details(payload: dict[str, Any]) -> MangaListEntry | None:
    """Build an entry from manga details that include ``my_list_status``.

    Returns ``None`` when the media exists but is not on the user's list.
    """
    details, on_list = manga_resolution_context_from_payload(payload)
    if not on_list:
        return None
    list_status = payload.get("my_list_status")
    if not isinstance(list_status, dict):
        raise ValueError("Manga details my_list_status was malformed")
    return MangaListEntry(
        mal_id=details.id,
        title=details.title,
        alternative_titles=details.alternative_titles,
        media_type=details.media_type,
        start_date=details.start_date,
        num_chapters=details.num_chapters,
        num_volumes=details.num_volumes,
        list_status=MangaListStatus.model_validate(list_status),
    )


def anime_list_entry_from_list_item(item: dict[str, Any]) -> AnimeListEntry:
    """Build an entry from a user animelist page item."""
    node = item.get("node")
    list_status = item.get("list_status")
    if not isinstance(node, dict) or not isinstance(list_status, dict):
        raise ValueError("Anime list item missing node or list_status")
    if "id" not in node:
        raise ValueError("Anime list node missing id")
    return AnimeListEntry(
        mal_id=int(node["id"]),
        title=node.get("title"),
        alternative_titles=(
            AlternativeTitles.model_validate(node["alternative_titles"])
            if isinstance(node.get("alternative_titles"), dict)
            else None
        ),
        media_type=node.get("media_type"),
        start_date=node.get("start_date"),
        num_episodes=node.get("num_episodes"),
        list_status=AnimeListStatus.model_validate(list_status),
    )


def manga_list_entry_from_list_item(item: dict[str, Any]) -> MangaListEntry:
    """Build an entry from a user mangalist page item."""
    node = item.get("node")
    list_status = item.get("list_status")
    if not isinstance(node, dict) or not isinstance(list_status, dict):
        raise ValueError("Manga list item missing node or list_status")
    if "id" not in node:
        raise ValueError("Manga list node missing id")
    return MangaListEntry(
        mal_id=int(node["id"]),
        title=node.get("title"),
        alternative_titles=(
            AlternativeTitles.model_validate(node["alternative_titles"])
            if isinstance(node.get("alternative_titles"), dict)
            else None
        ),
        media_type=node.get("media_type"),
        start_date=node.get("start_date"),
        num_chapters=node.get("num_chapters"),
        num_volumes=node.get("num_volumes"),
        list_status=MangaListStatus.model_validate(list_status),
    )


def _year_from_start_date(start_date: str | None) -> int | None:
    if not start_date:
        return None
    try:
        return int(start_date[:4])
    except (TypeError, ValueError):
        return None
