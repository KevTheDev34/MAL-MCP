# Audit, Idempotency, Recovery, and Undo (Phase 7)

Phase 7 strengthens the Phase 6 plan → confirm → apply → verify workflow with
durable audit records, server-side idempotency, interrupted-attempt recovery,
read-only history APIs, and field-level reverse plans.

Natural-language / LLM behavior remains deferred to Phase 8.

## Architecture

```text
API / diagnostic scripts
        ↓
CommandApplicationService
        ↓
HistoryService | ApplicationRecoveryService | UndoService
        ↓
ChangePlanExecutor (Phase 6) + CommandPlanRepository
        ↓
Resolver + MalClient
        ↓
MyAnimeList
```

## Persistence

Migration `0005_audit_idempotency_undo` extends Phase 6 tables:

| Addition | Purpose |
|---|---|
| `command_runs.source_type` | `api` or `diagnostic` |
| `command_runs.parent_command_id` | Undo-generated commands link to originals |
| `planned_items.reversion_status` | Derived undo eligibility summary |
| `application_attempts.idempotency_key` | Unique per-item apply key |
| `application_attempts.outcome_certainty` | `certain` / `uncertain` / `recovered` |
| `application_attempts.field_mismatches_json` | Verification mismatch detail |
| `item_reversions` | Original ↔ reverse item links |

### Immutability

- Original request, plan hash/content, and before/after snapshots are immutable.
- Application attempts are append-only (new rows for retries; finished payloads
  are not rewritten).
- Undo creates new command/plan/item/attempt/reversion rows.
- Ordinary command APIs never delete audit history.

### Sanitization

`commands/audit.py` strips tokens, Authorization headers, secrets, cookies, and
unbounded bodies before persistence. Error messages are redacted and truncated
(`AUDIT_MAX_ERROR_LENGTH`, default 500).

## Idempotency

Plan creation always creates a new command (no client merge key).

Confirmation remains idempotent for the same revision + plan hash.

Per-item apply key:

```text
apply:{user_id}:{plan_id}:{revision}:{planned_item_id}:{plan_hash}
```

The key is server-computed, unique in SQLite, and survives process restarts.
Repeated apply of a completed plan returns stored results without rewriting MAL.

## Recovery

`ApplicationRecoveryService.recover_plan` classifies interrupted attempts
(`writing`, `written_unverified`, uncertain outcomes) by reading current MAL
state:

| Classification | Action |
|---|---|
| Intended state present | Mark recovered verified; no write |
| Before state present | Record safe non-application; no automatic retry |
| Unexpected third state | Conflict; requires new plan |
| Remote lookup failure | Remain uncertain; no write |

Stale claim threshold: `APPLY_CLAIM_STALE_SECONDS` (default 120).

Invoke via `POST /commands/{plan_id}/recover` or `scripts/recover_plan.py`.
No background recovery job.

SQLite + in-process locks are not multi-instance safe.

## History API

| Method | Path |
|---|---|
| `GET` | `/history` |
| `GET` | `/history/{command_id}` |
| `GET` | `/commands/{plan_id}/history` |
| `POST` | `/history/{command_id}/undo-plan` |
| `POST` | `/commands/{plan_id}/items/{item_id}/undo-plan` |
| `POST` | `/commands/{plan_id}/recover` |

List endpoints do not call MAL. Snapshots are labeled as planned / verified /
recovery / undo-check observations — never as live current state unless a live
read was performed for undo or recover.

## Undo

Undo builds a **new** reverse plan. It never mutates original audit snapshots.

### Eligibility

- Item was verified (not noop / ambiguous / failed)
- Reliable before-state exists
- Entry was already on the list before the original change
- Not already fully reverted
- Diff(before, after) has reversible fields

### Newly added entries (Option B)

If `before.is_on_list` was false, undo is `not_reversible` with reason
`requires_entry_removal`. Entry deletion remains deferred to Phase 10. No
general delete endpoint is exposed.

### Field-level restore

Only fields changed by the original command are restored. Unrelated later MAL
edits are preserved. Same-field external changes produce a typed conflict and
do not create an applyable reverse item for that target.

### Lifecycle

```text
Undo request → eligibility + live conflict check → stored reverse plan
  → Phase 6 confirm → Phase 6 apply → verify → reversion link
```

Clients cannot supply arbitrary restored field values on undo endpoints.

Undo-of-undo works naturally by undoing the reverse command when eligible.
There is no separate redo feature.

## Diagnostic scripts

```bash
python scripts/show_command_history.py --limit 20
python scripts/show_command_history.py --command-id <uuid>
python scripts/create_undo_plan.py --command-id <uuid>
python scripts/recover_plan.py --plan-id <uuid> --revision 1
```

## Deferred

- LLM / chat / natural-language undo (Phase 8)
- History / undo UI (Phase 9)
- General deletion commands (Phase 10)
- Background recovery scheduler
- Multi-instance apply leasing
- Client-supplied plan-creation idempotency keys
