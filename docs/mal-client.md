# MAL API Client

Thin typed asynchronous HTTP client for MyAnimeList API v2. The client is the
only layer allowed to send authenticated MAL HTTP requests. It does **not**
perform title resolution, confirmation, planning, conversational logic, or
recommendations.

## Architecture

```text
Application / scripts
        │
        ▼
   MalClient  ──►  MalAccessTokenProvider (MalOAuthService.get_valid_access_token)
        │
        ▼
   httpx.AsyncClient  ──►  api.myanimelist.net/v2
```

Package layout:

| Module | Role |
|---|---|
| `backend/app/mal/client.py` | `MalClient` HTTP wrapper |
| `backend/app/mal/models.py` | Typed request/response models |
| `backend/app/mal/errors.py` | `MalError` taxonomy |
| `backend/app/mal/pagination.py` | List page / paging helpers |
| `backend/app/mal/token_provider.py` | Token provider protocol |

Phase 2 OAuth remains responsible for connect/disconnect, encryption, and
token refresh. The client only consumes `get_valid_access_token()`.

## Supported operations

| Client method | MAL endpoint |
|---|---|
| `get_current_user` | `GET /users/@me` |
| `search_anime` / `search_manga` | `GET /anime` / `GET /manga` |
| `get_anime` / `get_manga` | `GET /anime/{id}` / `GET /manga/{id}` |
| `get_anime_list_entry` / `get_manga_list_entry` | `GET /anime/{id}` or `/manga/{id}` with `fields=...,my_list_status` (missing `my_list_status` → `None`) |
| `update_anime_list_entry` / `update_manga_list_entry` | `PATCH .../my_list_status` (form-urlencoded) |
| `delete_anime_list_entry` / `delete_manga_list_entry` | `DELETE .../my_list_status` (`404` = no-op) |
| `iter_anime_list` / `iter_manga_list` | `GET /users/@me/animelist` / `mangalist` + `paging.next` |

There are **no** public FastAPI routes for these operations in Phase 3.

## Authentication integration

1. Before each authenticated call, `MalClient` asks the token provider for a
   valid access token (proactive refresh when near expiry).
2. Refresh is serialized with a process-scoped lock inside `MalOAuthService`
   (single-worker local MVP).
3. On HTTP `401`, the client force-refreshes once and retries the request once.
4. A second `401` becomes `MalAuthenticationError`.
5. Definitive refresh failures clear stored tokens and require reconnect.
   Transient refresh failures (network / 5xx) leave credentials intact and
   surface as `MalTemporaryError`.

Tokens never appear in logs, exception messages, or script output.

## Typed models

Minimum fields for later title resolution and planning are modeled:

- Identity: MAL ID, canonical title, English/Japanese/alternative titles
- Media: format, start date / release year, episode / chapter / volume totals
- List: status, score, progress, rewatch/reread flags

Updates use allowlisted models (`AnimeListUpdate`, `MangaListUpdate`) with
`extra="forbid"`. Unsupported fields are rejected locally.

### MAL field-name quirk

| Context | Episode progress field |
|---|---|
| List / status **responses** | `num_episodes_watched` |
| Update **requests** | `num_watched_episodes` |

## Error mapping

| Condition | Exception |
|---|---|
| Missing / reconnect-required credentials | `MalAuthenticationError` |
| HTTP 401 after refresh retry | `MalAuthenticationError` |
| HTTP 403 | `MalAuthorizationError` |
| HTTP 404 (except list-entry lookup → `None`) | `MalNotFoundError` |
| HTTP 400 | `MalValidationError` |
| HTTP 429 | `MalRateLimitError` (`retry_after` when available) |
| HTTP 5xx / timeout / connection after retries | `MalTemporaryError` |
| Malformed JSON / missing required fields | `MalUnexpectedResponseError` |

## Retry policy

Documented in `backend/app/mal/client.py`:

- Max attempts for safe requests: 3
- Backoff: `0.5s * 2^(attempt-1)`; honor `Retry-After` on 429 (capped at 30s)
- **GET / DELETE**: retry network errors, timeouts, 429, 502/503/504
- **PATCH**: retry only 429 and clear connection failures; do **not** retry
  after timeout or 5xx (uncertain apply)
- Auth: at most one force-refresh-and-retry cycle per logical call
- **DELETE 404**: treated as success (idempotent no-op)

## Pagination

`iter_anime_list` / `iter_manga_list` are async iterators:

1. Fetch the first page (`limit=100`)
2. Yield typed entries from `data[].node` + `data[].list_status`
3. Follow absolute `paging.next` until absent
4. Malformed paging or items raise `MalUnexpectedResponseError`

## Dependency injection

```python
from backend.app.dependencies import get_mal_client

# FastAPI:
# async def handler(client: Annotated[MalClient, Depends(get_mal_client)]): ...
```

Scripts construct `MalOAuthService` + `MalClient` with a DB session directly.

## Running mocked tests

```bash
pytest
pytest backend/tests/contract -q
pytest backend/tests/unit/test_mal_models.py backend/tests/unit/test_mal_client_security.py -q
ruff check .
mypy backend/app
```

## Manual reversible integration test

Requires a connected MAL account (see [`docs/oauth-setup.md`](oauth-setup.md)).

1. Pick a harmless anime or manga **already on your list** by exact MAL ID.
2. Run:

```bash
python scripts/mal_reversible_list_update.py \
  --media anime \
  --mal-id 9253 \
  --field score \
  --value 8
```

3. The script prints the current state (no tokens).
4. Type `yes` to confirm.
5. It applies the update, re-reads, verifies, restores the original value,
   re-reads, and verifies restoration.
6. Exit code `0` means success. Non-zero means verification or MAL failure.

Guards:

- Refuses to run when `APP_ENV=production` unless `--i-know-what-im-doing`
- Does **not** create missing list entries
- Does **not** delete entries
- Never prints credentials or tokens

## Known MAL API limitations

- Default responses omit most fields; the client always requests an explicit
  `fields` list.
- List updates must be `application/x-www-form-urlencoded`, not JSON.
- **`GET /{media}/{id}/my_list_status` is not supported** (MAL returns HTTP
  405). List membership is read via `GET /{media}/{id}?fields=...,my_list_status`.
  Absent `my_list_status` means the title is not on the user's list. Unknown
  media IDs still return HTTP 404 → `MalNotFoundError`.
- Response vs request episode field names differ (see quirk above).
- Rate-limit headers are inconsistent; `Retry-After` is best-effort.
- Multi-process refresh races are out of scope for the local single-worker MVP.
- A PATCH timeout after MAL applied the write can leave remote state changed
  without client confirmation; later phases own read-after-write verification.
