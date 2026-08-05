# Command Workflow (Phase 6)

Deterministic plan → confirm → apply → verify for structured MAL list changes.
Natural-language interpretation is deferred to Phase 8.

## Architecture

```text
API routes (/commands/*)
    ↓
CommandApplicationService
    ↓
ChangePlanner | PlanConfirmationService | ChangePlanExecutor
    ↓
TitleResolver + MalClient + CommandPlanRepository + Clock
    ↓
MyAnimeList
```

Rules:

- Route handlers stay thin.
- The planner never writes to MAL.
- Apply uses only the stored confirmed plan (no client-supplied after-state).
- Every successful write is followed by a read-after-write verification.
- Success is never claimed on verification failure.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/commands/plan` | Create a persisted plan from structured changes |
| `GET` | `/commands/{plan_id}` | Fetch plan + item outcomes (+ apply results) |
| `POST` | `/commands/{plan_id}/confirm` | Bind confirmation to revision + plan hash |
| `POST` | `/commands/{plan_id}/apply` | Apply the stored confirmed plan |
| `POST` | `/commands/{plan_id}/cancel` | Cancel → `rejected` |

User identity comes from the singleton local user dependency. Request bodies must
not include user IDs.

### Plan request

```json
{
  "original_text": null,
  "changes": [
    {
      "title": "Steins;Gate",
      "media_type": "anime",
      "status": "completed",
      "score": 9
    }
  ]
}
```

Validation:

- At least one change; at most `MAX_PLAN_CHANGES` (default 25)
- `RequestedChange` forbids unknown fields and enforces media-specific rules
- No MAL IDs in this path (title resolution only)

## Per-item planning outcomes

| Kind | Applyable |
|---|---|
| `ready` | Yes |
| `noop` | No write |
| `ambiguous` | No |
| `not_found` | No |
| `invalid` | No |
| `lookup_failed` | No |

Policy:

- All outcomes are stored and returned.
- Ambiguous/invalid items do not block independent ready items.
- Only `ready` items are applyable.
- Unresolved-only / all-noop plans are not confirmable.
- Clarifying unresolved items requires a new `POST /commands/plan`.

## Desired-state calculation

`commands.propose.calculate_proposed_state` applies a `RequestedChange` onto a
normalized `CurrentListState`:

- Preserves unrequested fields
- Never invents scores or unknown totals
- Fills progress to reliable known totals when marking completed
- Warns on score/progress/status overwrite, unknown completion totals, ongoing
  titles marked completed, and not-previously-on-list
- Rejects progress beyond known totals and media-mismatched fields

Domain → MAL patches are derived by diffing before/after in
`mal.domain_mapping.proposed_*_state_to_update`.

## Duplicate targets

After resolution, requests that share `(media_type, mal_id)` are merged when
compatible. Conflicting field values produce `invalid` items. A plan never
schedules two writes to the same MAL ID.

## Persistence

Tables (migration `0004_command_plans`):

- `command_runs`
- `change_plans` (immutable revision + `plan_hash` + expiry)
- `planned_items`
- `application_attempts`

Cancel uses `CommandState.rejected` with `cancel_reason=canceled_by_user`.

## Confirmation binding

Phase 6 computes a SHA-256 `plan_hash` over canonical plan contents (IDs,
revision, per-item outcomes/before/after/warnings). Confirm requires matching
`revision` + `plan_hash` against the stored plan.

Confirmed-but-unapplied plans still expire. Once apply has started
(`applying`), completion may finish after wall-clock expiry.

## Apply workflow

1. Claim plan (`awaiting_confirmation` → `applying`)
2. For each ready item in `apply_order`:
   - Re-read current MAL state
   - Compare full domain before-state (stale conflict → skip write)
   - PATCH by exact MAL ID
   - Persist `written_unverified`
   - Re-read and verify intended fields
3. Continue independent item failures
4. Stop remaining writes on authentication loss
5. Overall state: `verified` | `partially_applied` | `failed`

Repeated apply of a completed plan returns the stored result without rewriting.

## Failure recovery

If a process dies after write but before verification, retry finds
`written_unverified`, re-reads MAL, and marks verified or
`verification_unknown` without a blind second write.

## Diagnostic script

```bash
python scripts/plan_mal_change.py \
  --media anime \
  --title "Steins;Gate" \
  --score 8

python scripts/plan_mal_change.py \
  --media anime \
  --title "Hunter x Hunter" \
  --status completed \
  --plan-only
```

The script uses `CommandApplicationService` (same path as the API).

## Phase 7 extensions

See [`docs/audit-undo.md`](audit-undo.md) for:

- Durable audit sanitization
- Per-item idempotency keys
- Application recovery
- History endpoints
- Field-level undo / reverse plans

## Still deferred

- Background retries
- Conversational clarification → automatic revision API
- Multi-instance apply leasing
- Compensation after partial bulk failure
- Natural-language interpretation (Phase 8)
