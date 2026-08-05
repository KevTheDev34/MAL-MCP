"""Thin typed asynchronous MAL HTTP client.

Responsibilities: bearer injection, token refresh integration, timeouts,
form-encoded updates, typed parsing, pagination, error translation, bounded
retries, and sanitized logging.

Non-responsibilities: title resolution, confirmation, planning, LLM, or
recommendations.

Retry policy (conservative):
- Safe methods (GET, DELETE): retry network errors, timeouts, 429, 502/503/504
  up to MAX_ATTEMPTS with exponential backoff; honor Retry-After when present
  (capped).
- PATCH: retry only 429 and connection failures that clearly never received a
  response; do not retry after timeout or 5xx (uncertain apply).
- Authentication: at most one force-refresh-and-retry cycle per logical call.
- DELETE 404 is treated as success (idempotent no-op).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.auth.errors import (
    MalNotConnectedError,
    MalReconnectRequiredError,
    OAuthTokenTemporaryError,
)
from backend.app.config import Settings
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalAuthorizationError,
    MalError,
    MalNotFoundError,
    MalRateLimitError,
    MalTemporaryError,
    MalUnexpectedResponseError,
    MalValidationError,
)
from backend.app.mal.models import (
    AnimeDetails,
    AnimeListEntry,
    AnimeListUpdate,
    AnimeSearchResult,
    MalUser,
    MangaDetails,
    MangaListEntry,
    MangaListUpdate,
    MangaSearchResult,
    anime_list_entry_from_details,
    anime_list_entry_from_list_item,
    anime_list_entry_from_status,
    manga_list_entry_from_details,
    manga_list_entry_from_list_item,
    manga_list_entry_from_status,
)
from backend.app.mal.pagination import parse_list_page_data, parse_paging
from backend.app.mal.token_provider import MalAccessTokenProvider

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.5
MAX_RETRY_AFTER_SECONDS = 30.0
DEFAULT_LIST_PAGE_LIMIT = 100

ANIME_SEARCH_FIELDS = (
    "id,title,alternative_titles,media_type,start_date,num_episodes,status"
)
MANGA_SEARCH_FIELDS = (
    "id,title,alternative_titles,media_type,start_date,num_chapters,num_volumes,status"
)
# MAL does not support GET on /{media}/{id}/my_list_status (returns 405).
# Read list membership via details + fields=my_list_status instead.
ANIME_LIST_ENTRY_FIELDS = (
    f"{ANIME_SEARCH_FIELDS},"
    "my_list_status{status,score,num_episodes_watched,is_rewatching,"
    "updated_at,start_date,finish_date}"
)
MANGA_LIST_ENTRY_FIELDS = (
    f"{MANGA_SEARCH_FIELDS},"
    "my_list_status{status,score,num_chapters_read,num_volumes_read,is_rereading,"
    "updated_at,start_date,finish_date}"
)
ANIME_LIST_FIELDS = (
    "list_status{status,score,num_episodes_watched,is_rewatching,"
    "updated_at,start_date,finish_date},"
    "alternative_titles,media_type,start_date,num_episodes"
)
MANGA_LIST_FIELDS = (
    "list_status{status,score,num_chapters_read,num_volumes_read,is_rereading,"
    "updated_at,start_date,finish_date},"
    "alternative_titles,media_type,start_date,num_chapters,num_volumes"
)

RequestMethod = Literal["GET", "PATCH", "DELETE"]
TModel = TypeVar("TModel", bound=BaseModel)


class MalClient:
    """Authenticated MAL API v2 client."""

    def __init__(
        self,
        *,
        settings: Settings,
        token_provider: MalAccessTokenProvider,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._token_provider = token_provider
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds
        )
        self._base_url = settings.mal_api_base_url.rstrip("/")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def get_current_user(self) -> MalUser:
        payload = await self._request_json("GET", "/users/@me")
        return self._validate(MalUser, payload)

    async def search_anime(
        self,
        query: str,
        limit: int = 10,
    ) -> list[AnimeSearchResult]:
        payload = await self._request_json(
            "GET",
            "/anime",
            params={"q": query, "limit": limit, "fields": ANIME_SEARCH_FIELDS},
        )
        items = parse_list_page_data(payload)
        results: list[AnimeSearchResult] = []
        for item in items:
            node = item.get("node", item)
            if not isinstance(node, dict):
                raise MalUnexpectedResponseError("Anime search item was malformed")
            results.append(self._validate(AnimeSearchResult, node))
        return results

    async def search_manga(
        self,
        query: str,
        limit: int = 10,
    ) -> list[MangaSearchResult]:
        payload = await self._request_json(
            "GET",
            "/manga",
            params={"q": query, "limit": limit, "fields": MANGA_SEARCH_FIELDS},
        )
        items = parse_list_page_data(payload)
        results: list[MangaSearchResult] = []
        for item in items:
            node = item.get("node", item)
            if not isinstance(node, dict):
                raise MalUnexpectedResponseError("Manga search item was malformed")
            results.append(self._validate(MangaSearchResult, node))
        return results

    async def get_anime(self, anime_id: int) -> AnimeDetails:
        payload = await self._request_json(
            "GET",
            f"/anime/{anime_id}",
            params={"fields": ANIME_SEARCH_FIELDS},
        )
        return self._validate(AnimeDetails, payload)

    async def get_manga(self, manga_id: int) -> MangaDetails:
        payload = await self._request_json(
            "GET",
            f"/manga/{manga_id}",
            params={"fields": MANGA_SEARCH_FIELDS},
        )
        return self._validate(MangaDetails, payload)

    async def get_anime_list_entry(self, anime_id: int) -> AnimeListEntry | None:
        """Return the user's anime list entry, or None if not on the list.

        MAL does not allow GET on ``/anime/{id}/my_list_status`` (HTTP 405).
        Membership is read from anime details with ``fields=...,my_list_status``.
        """
        payload = await self._request_json(
            "GET",
            f"/anime/{anime_id}",
            params={"fields": ANIME_LIST_ENTRY_FIELDS},
        )
        try:
            return anime_list_entry_from_details(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise MalUnexpectedResponseError(
                "Anime list status response was invalid"
            ) from exc

    async def get_manga_list_entry(self, manga_id: int) -> MangaListEntry | None:
        """Return the user's manga list entry, or None if not on the list.

        MAL does not allow GET on ``/manga/{id}/my_list_status`` (HTTP 405).
        Membership is read from manga details with ``fields=...,my_list_status``.
        """
        payload = await self._request_json(
            "GET",
            f"/manga/{manga_id}",
            params={"fields": MANGA_LIST_ENTRY_FIELDS},
        )
        try:
            return manga_list_entry_from_details(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise MalUnexpectedResponseError(
                "Manga list status response was invalid"
            ) from exc

    async def update_anime_list_entry(
        self,
        anime_id: int,
        fields: AnimeListUpdate,
    ) -> AnimeListEntry:
        payload = await self._request_json(
            "PATCH",
            f"/anime/{anime_id}/my_list_status",
            data=fields.to_form_data(),
        )
        try:
            return anime_list_entry_from_status(anime_id, payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise MalUnexpectedResponseError(
                "Anime list update response was invalid"
            ) from exc

    async def update_manga_list_entry(
        self,
        manga_id: int,
        fields: MangaListUpdate,
    ) -> MangaListEntry:
        payload = await self._request_json(
            "PATCH",
            f"/manga/{manga_id}/my_list_status",
            data=fields.to_form_data(),
        )
        try:
            return manga_list_entry_from_status(manga_id, payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise MalUnexpectedResponseError(
                "Manga list update response was invalid"
            ) from exc

    async def delete_anime_list_entry(self, anime_id: int) -> None:
        await self._request(
            "DELETE",
            f"/anime/{anime_id}/my_list_status",
            expect_json=False,
            not_found_ok=True,
        )

    async def delete_manga_list_entry(self, manga_id: int) -> None:
        await self._request(
            "DELETE",
            f"/manga/{manga_id}/my_list_status",
            expect_json=False,
            not_found_ok=True,
        )

    async def iter_anime_list(
        self,
        *,
        status: str | None = None,
    ) -> AsyncIterator[AnimeListEntry]:
        params: dict[str, str | int] = {
            "limit": DEFAULT_LIST_PAGE_LIMIT,
            "fields": ANIME_LIST_FIELDS,
        }
        if status is not None:
            params["status"] = status
        async for item in self._iter_list_pages("/users/@me/animelist", params):
            try:
                yield anime_list_entry_from_list_item(item)
            except (ValidationError, ValueError, TypeError) as exc:
                raise MalUnexpectedResponseError(
                    "Anime list page item was invalid"
                ) from exc

    async def iter_manga_list(
        self,
        *,
        status: str | None = None,
    ) -> AsyncIterator[MangaListEntry]:
        params: dict[str, str | int] = {
            "limit": DEFAULT_LIST_PAGE_LIMIT,
            "fields": MANGA_LIST_FIELDS,
        }
        if status is not None:
            params["status"] = status
        async for item in self._iter_list_pages("/users/@me/mangalist", params):
            try:
                yield manga_list_entry_from_list_item(item)
            except (ValidationError, ValueError, TypeError) as exc:
                raise MalUnexpectedResponseError(
                    "Manga list page item was invalid"
                ) from exc

    async def _iter_list_pages(
        self,
        path: str,
        params: Mapping[str, str | int],
    ) -> AsyncIterator[dict[str, Any]]:
        next_path: str | None = path
        next_params: Mapping[str, str | int] | None = params
        absolute_url: str | None = None
        while next_path is not None or absolute_url is not None:
            if absolute_url is not None:
                payload = await self._request_json(
                    "GET",
                    absolute_url,
                    absolute=True,
                )
            else:
                assert next_path is not None
                payload = await self._request_json(
                    "GET",
                    next_path,
                    params=dict(next_params or {}),
                )
            for item in parse_list_page_data(payload):
                yield item
            paging = parse_paging(payload)
            if not paging.next:
                break
            absolute_url = paging.next
            next_path = None
            next_params = None

    async def _request_json(
        self,
        method: RequestMethod,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        absolute: bool = False,
    ) -> dict[str, Any]:
        response = await self._request(
            method,
            path,
            params=params,
            data=data,
            expect_json=True,
            absolute=absolute,
        )
        assert response is not None
        return self._parse_json_object(response)

    async def _request(
        self,
        method: RequestMethod,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        expect_json: bool = True,
        not_found_ok: bool = False,
        absolute: bool = False,
    ) -> httpx.Response | None:
        url = path if absolute else f"{self._base_url}{path}"
        auth_retried = False
        attempt = 0

        while True:
            try:
                access_token = await self._token_provider.get_valid_access_token(
                    force_refresh=False
                )
            except MalNotConnectedError as exc:
                raise MalAuthenticationError("MAL is not connected") from exc
            except MalReconnectRequiredError as exc:
                raise MalAuthenticationError("MAL reconnect is required") from exc
            except OAuthTokenTemporaryError as exc:
                raise MalTemporaryError("MAL token refresh temporarily failed") from exc

            headers = {"Authorization": f"Bearer {access_token}"}
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"

            try:
                response = await self._http.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                if self._should_retry_transport(method, attempt):
                    attempt += 1
                    await self._backoff(attempt)
                    continue
                logger.warning(
                    "MAL request timed out method=%s path=%s",
                    method,
                    self._safe_path(url),
                )
                raise MalTemporaryError("MAL request timed out") from exc
            except httpx.TransportError as exc:
                # Connection failures before a response are safe to retry for
                # PATCH as well as GET/DELETE.
                if attempt + 1 < MAX_ATTEMPTS:
                    attempt += 1
                    await self._backoff(attempt)
                    continue
                logger.warning(
                    "MAL request connection failed method=%s path=%s error=%s",
                    method,
                    self._safe_path(url),
                    type(exc).__name__,
                )
                raise MalTemporaryError("MAL request connection failed") from exc

            if response.status_code == 401 and not auth_retried:
                auth_retried = True
                try:
                    await self._token_provider.get_valid_access_token(
                        force_refresh=True
                    )
                except MalNotConnectedError as exc:
                    raise MalAuthenticationError("MAL is not connected") from exc
                except MalReconnectRequiredError as exc:
                    raise MalAuthenticationError("MAL reconnect is required") from exc
                except OAuthTokenTemporaryError as exc:
                    raise MalTemporaryError(
                        "MAL token refresh temporarily failed"
                    ) from exc
                logger.info(
                    "MAL request retried after auth refresh method=%s path=%s",
                    method,
                    self._safe_path(url),
                )
                continue

            if response.status_code == 404 and not_found_ok:
                if expect_json:
                    return response
                return None

            if self._should_retry_status(method, response.status_code, attempt):
                attempt += 1
                wait = self._retry_wait_seconds(response, attempt)
                logger.info(
                    "MAL request retry method=%s path=%s status=%s attempt=%s",
                    method,
                    self._safe_path(url),
                    response.status_code,
                    attempt,
                )
                await asyncio.sleep(wait)
                continue

            if response.status_code >= 400:
                raise self._map_status_error(response)

            if expect_json and response.status_code == 204:
                raise MalUnexpectedResponseError(
                    "MAL returned an empty success response"
                )
            if not expect_json:
                return None
            return response

    def _should_retry_transport(self, method: RequestMethod, attempt: int) -> bool:
        if attempt + 1 >= MAX_ATTEMPTS:
            return False
        # Timeouts after PATCH are uncertain — do not retry.
        return method in ("GET", "DELETE")

    def _should_retry_status(
        self,
        method: RequestMethod,
        status_code: int,
        attempt: int,
    ) -> bool:
        if attempt + 1 >= MAX_ATTEMPTS:
            return False
        if status_code == 429:
            return True
        if status_code in {502, 503, 504}:
            return method in ("GET", "DELETE")
        return False

    def _retry_wait_seconds(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass
        return float(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(float(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))))

    def _map_status_error(self, response: httpx.Response) -> MalError:
        status = response.status_code
        path = self._safe_path(str(response.request.url))
        logger.warning(
            "MAL request failed method=%s path=%s status=%s",
            response.request.method,
            path,
            status,
        )
        if status == 400:
            return MalValidationError("MAL rejected the request as invalid")
        if status == 401:
            return MalAuthenticationError("MAL authentication failed")
        if status == 403:
            return MalAuthorizationError("MAL authorization failed")
        if status == 404:
            return MalNotFoundError("MAL resource was not found")
        if status == 429:
            retry_after: float | None = None
            raw = response.headers.get("Retry-After")
            if raw is not None:
                try:
                    retry_after = min(float(raw), MAX_RETRY_AFTER_SECONDS)
                except ValueError:
                    retry_after = None
            return MalRateLimitError(
                "MAL rate limit exceeded",
                retry_after=retry_after,
            )
        if status in {500, 502, 503, 504}:
            return MalTemporaryError("MAL server returned a temporary error")
        return MalUnexpectedResponseError(f"MAL returned unexpected status {status}")

    def _parse_json_object(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MalUnexpectedResponseError("MAL response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise MalUnexpectedResponseError("MAL response JSON was not an object")
        return payload

    def _validate(self, model: type[TModel], payload: dict[str, Any]) -> TModel:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise MalUnexpectedResponseError(
                "MAL response was missing required fields"
            ) from exc

    @staticmethod
    def _safe_path(url: str) -> str:
        parsed = urlparse(url)
        return parsed.path or url
