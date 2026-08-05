# Implementation Checklist

Use this checklist as the authoritative build tracker.

## Phase 0 — Behavioral specification

- [x] Create `docs/behavior.md`
- [x] Define supported intents
- [x] Define status mappings
- [x] Define title ambiguity policy
- [x] Define confirmation policy
- [x] Define bulk failure policy
- [x] Define no-op behavior
- [x] Define overwrite warnings
- [x] Define undo conflict behavior

## Phase 1 — Project foundation

- [x] Initialize Python 3.12 project
- [x] Add FastAPI
- [x] Add Pydantic settings
- [x] Add SQLAlchemy
- [x] Add Alembic
- [x] Add SQLite
- [x] Add structured logging
- [x] Add `/health`
- [x] Add pytest
- [x] Add ruff
- [x] Add mypy
- [x] Add Dockerfile
- [x] Add Docker Compose
- [x] Add `.env.example`
- [x] Add initial README
- [x] Add CI configuration

## Phase 2 — MAL OAuth

- [x] Implement OAuth state generation
- [x] Implement authorization redirect
- [x] Implement callback
- [x] Validate state
- [x] Exchange code for tokens
- [x] Encrypt tokens
- [x] Store MAL user identity
- [x] Refresh tokens
- [x] Add disconnect
- [x] Add connection status
- [x] Test expired and invalid state
- [x] Verify tokens never appear in logs

## Phase 3 — MAL client

- [x] Implement current-user call
- [x] Implement anime search
- [x] Implement manga search
- [x] Implement anime details
- [x] Implement manga details
- [x] Implement anime list lookup
- [x] Implement manga list lookup
- [x] Implement anime update
- [x] Implement manga update
- [x] Implement list pagination
- [x] Implement error taxonomy
- [x] Implement timeouts
- [x] Implement bounded retries
- [x] Add contract tests
- [x] Perform reversible real-account test

## Phase 4 — Domain model

- [x] Add media enums
- [x] Add status enums
- [x] Add command-state enum
- [x] Add requested-change model
- [x] Add resolved-media model
- [x] Add planned-change model
- [x] Add change-plan model
- [x] Add media-specific validation
- [ ] Add database migrations *(deferred to Phase 6 — no unused command/plan tables in Phase 4; see `docs/domain.md`)*

## Phase 5 — Title resolver

- [x] Normalize title strings
- [x] Search both media types when unspecified
- [x] Enrich candidates
- [x] Score candidates
- [x] Store confidence reasons
- [x] Define thresholds
- [x] Return ambiguity candidates
- [x] Add title aliases
- [x] Build resolver test corpus
- [x] Test remakes and seasons
- [x] Test anime/manga collisions
- [x] Test movie/TV collisions

## Phase 6 — Plan and apply

- [ ] Add `POST /commands/plan`
- [ ] Read current MAL state
- [ ] Build before/after state
- [ ] Add validation warnings
- [ ] Detect no-op changes
- [ ] Store plan revisions
- [ ] Add plan expiration
- [ ] Add confirmation endpoint
- [ ] Add apply endpoint
- [ ] Re-read current state before apply
- [ ] Detect stale plan conflicts
- [ ] Apply update
- [ ] Verify with read-after-write
- [ ] Report partial bulk outcomes

## Phase 7 — Audit, idempotency, undo

- [ ] Add plan hashing
- [ ] Add idempotency key
- [ ] Prevent replay
- [ ] Store request and verified results
- [ ] Add history endpoint
- [ ] Implement reverse plan
- [ ] Detect external changes before undo
- [ ] Verify undo
- [ ] Preserve audit records

## Phase 8 — LLM interpreter

- [ ] Add provider abstraction
- [ ] Add OpenAI implementation
- [ ] Define strict tool schemas
- [ ] Add orchestrator prompt
- [ ] Add natural-language extraction
- [ ] Add clarification handling
- [ ] Add confirmation handling
- [ ] Store conversation state server-side
- [ ] Add LLM evaluation dataset
- [ ] Add adversarial cases
- [ ] Ensure model cannot call MAL client directly

## Phase 9 — Web UI

- [ ] Add chat page
- [ ] Add MAL connection controls
- [ ] Add ambiguity selection UI
- [ ] Add preview card
- [ ] Add confirm/cancel controls
- [ ] Add bulk preview
- [ ] Add history page
- [ ] Add undo controls
- [ ] Add loading state
- [ ] Add partial failure state
- [ ] Add disconnected state

## Phase 10 — Expanded management

- [ ] Relative progress increments
- [ ] Episode ranges
- [ ] Chapter ranges
- [ ] Start and finish dates
- [ ] Bulk historical updates
- [ ] Corrections
- [ ] Rewatching
- [ ] Rereading
- [ ] On-hold
- [ ] Dropped
- [ ] Optional deletion with strict confirmation

## Phase 11 — Synchronization

- [ ] Full anime sync
- [ ] Full manga sync
- [ ] Incremental sync
- [ ] Cache upserts
- [ ] Removed-entry detection
- [ ] External-change detection
- [ ] Sync status endpoint
- [ ] Sync status UI

## Phase 12 — Recommendations

- [ ] Candidate filtering
- [ ] Exclude completed entries
- [ ] Respect dropped exclusions
- [ ] Length filters
- [ ] Genre filters
- [ ] Taste-profile calculations
- [ ] Candidate ranking
- [ ] LLM recommendation explanations
- [ ] Session preference handling
- [ ] Add-to-list flow through existing plan system

## Phase 13 — Hardening

- [ ] CSRF protection
- [ ] Secure cookies
- [ ] Secret redaction tests
- [ ] Database backup
- [ ] Restore test
- [ ] Health checks
- [ ] Reverse proxy
- [ ] LAN-only deployment
- [ ] Docker volumes
- [ ] Raspberry Pi documentation
- [ ] Token refresh monitoring
- [ ] Failure recovery tests

## Phase 14 — Additional adapters

- [ ] MCP adapter
- [ ] Telegram or Discord adapter
- [ ] Mobile-friendly UI
- [ ] Optional private remote access
- [ ] Scheduled sync
