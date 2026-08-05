# Application Domain Model

Phase 4 defines the typed application-domain layer used by later title
resolution, planning, apply, audit, and LLM tool calling.

## Transport models versus domain models

| Layer | Package | Role |
|---|---|---|
| MAL transport | `backend.app.mal.models` | Data sent to or returned by the MAL API (raw field names, form encoding, pagination) |
| Application domain | `backend.app.domain` | What the assistant understands, validates, plans, and records |

Services must not depend on raw MAL response models when a domain representation
is appropriate. Conversion lives at the boundary in
`backend.app.mal.domain_mapping` so the pure domain package never imports the
MAL HTTP client, SQLAlchemy, FastAPI, or LLM code.

```text
mal.models  ──►  mal.domain_mapping  ──►  domain.*
domain.*    ──X──►  mal | db | api | auth | llm
```

## Package structure

| Module | Contents |
|---|---|
| `domain.enums` | `MediaType`, `AnimeStatus`, `MangaStatus`, `CommandState`, error/warning codes |
| `domain.requests` | `RequestedChange` |
| `domain.media` | `ResolvedMedia` |
| `domain.state` | `CurrentListState`, `ProposedListState` |
| `domain.plans` | `PlanWarning`, `PlannedChange`, `ChangePlan` |
| `domain.transitions` | `ALLOWED_TRANSITIONS`, `validate_transition` |
| `domain.errors` | `DomainError`, `DomainValidationError` |
| `domain.serialization` | `canonical_domain_json` |

## Status and media enums

- `MediaType`: `anime`, `manga`
- `AnimeStatus`: `watching`, `completed`, `on_hold`, `dropped`, `plan_to_watch`
- `MangaStatus`: `reading`, `completed`, `on_hold`, `dropped`, `plan_to_read`

Rewatching / rereading are **not** domain request concepts in Phase 4. They
remain on MAL transport models (`is_rewatching` / `is_rereading`) for Phase 10.

## Requested-change validation

`RequestedChange` represents one user-requested change before title resolution.

Rules:

- Title must not be empty or whitespace-only (stored stripped)
- At least one mutable field: status, score, or progress
- Score is an integer from 1 through 10 when present
- Progress values cannot be negative
- When `media_type` is anime: no chapter/volume progress; status must be anime
- When `media_type` is manga: no episode progress; status must be manga
- When `media_type` is unknown: media-specific checks are deferred
- No inference of missing values; unsupported status strings are rejected

Start/finish dates are intentionally omitted from the domain request model until
Phase 10. MAL transport still supports `start_date` / `finish_date`.

## Current state versus proposed state

`CurrentListState` is the normalized remote list snapshot for one item,
including an explicit not-on-list form (`is_on_list=False` with all mutable
fields `None`).

`ProposedListState` is the desired end state after a future apply.

Domain scores never use `0`. Unscored is `None`. MAL transport score `0` maps
to domain `None` in converters.

### Unchanged versus cleared fields

Phase 4 uses **full before/after snapshots** (not UNSET sentinels):

| Concept | Representation |
|---|---|
| Unchanged | `before.field == after.field` |
| Intentional set | `after.field` differs from `before.field` |
| Intentional clear | `before.field` is set and `after.field is None` (score/progress) |

Phase 6 will derive MAL write patches (`AnimeListUpdate` / `MangaListUpdate`)
by diffing before → after.

## Command lifecycle states

`CommandState` values:

`received` → `parsed` → `resolving` ⇄ `awaiting_clarification` → `planned` →
`awaiting_confirmation` → `applying` → (`verified` | `partially_applied` |
`failed`)

Cancel / reject paths use `rejected`. Undo uses `verified` /
`partially_applied` → `reverted`.

`validate_transition(current, target)` enforces the graph. Same-state and
unknown edges raise `DomainValidationError` with
`INVALID_STATE_TRANSITION`. No persistence or execution happens in Phase 4.

## MAL-to-domain conversion boundary

`backend.app.mal.domain_mapping` provides:

- `anime_details_to_resolved_media` / `manga_details_to_resolved_media`
- `anime_list_entry_to_current_state` / `manga_list_entry_to_current_state`
- `not_on_list_state` / `list_entry_or_none_to_current_state`

Rules:

- Missing MAL totals stay `None` (never coerced to `0`)
- Absent list entries become explicit not-on-list domain state
- Unknown MAL status strings fail with `INVALID_STATUS`

Domain → MAL update mapping lives in Phase 6 (`proposed_*_state_to_update`).

## Serialization

`canonical_domain_json(model)` dumps with Pydantic JSON mode, sorted keys, and
compact separators. Enums serialize to stable strings. Datetimes must be
timezone-aware. Phase 6 plan hashing uses a dedicated command-layer helper;
Phase 7 may expand audit hashing with this domain helper.

## Persistence

Phase 4 does **not** add ORM tables or Alembic migrations for commands/plans.
Serializable domain objects are the contract. Phase 6 adds `command_runs` /
`change_plans` / `planned_items` / `application_attempts` — see
[`docs/commands.md`](commands.md).

Phase 5 adds `title_aliases` for user-specific shortcuts (see
[`docs/resolver.md`](resolver.md)). Aliases live outside the pure domain
package.

## What Phase 4 intentionally does not implement

- Title normalization, candidate scoring, aliases, confidence calculation
  (implemented in Phase 5 — [`docs/resolver.md`](resolver.md))
- Plan construction, confirmation, expiration enforcement, MAL write execution
  (implemented in Phase 6 — [`docs/commands.md`](commands.md))
- Audit history and undo
- Natural-language / OpenAI integration
- Recommendations, React UI
- Start/finish dates and rewatch/reread as domain request fields
