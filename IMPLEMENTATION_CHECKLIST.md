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

- [ ] Implement current-user call
- [ ] Implement anime search
- [ ] Implement manga search
- [ ] Implement anime details
- [ ] Implement manga details
- [ ] Implement anime list lookup
- [ ] Implement manga list lookup
- [ ] Implement anime update
- [ ] Implement manga update
- [ ] Implement list pagination
- [ ] Implement error taxonomy
- [ ] Implement timeouts
- [ ] Implement bounded retries
- [ ] Add contract tests
- [ ] Perform reversible real-account test

## Phase 4 — Domain model

- [ ] Add media enums
- [ ] Add status enums
- [ ] Add command-state enum
- [ ] Add requested-change model
- [ ] Add resolved-media model
- [ ] Add planned-change model
- [ ] Add change-plan model
- [ ] Add media-specific validation
- [ ] Add database migrations

## Phase 5 — Title resolver

- [ ] Normalize title strings
- [ ] Search both media types when unspecified
- [ ] Enrich candidates
- [ ] Score candidates
- [ ] Store confidence reasons
- [ ] Define thresholds
- [ ] Return ambiguity candidates
- [ ] Add title aliases
- [ ] Build resolver test corpus
- [ ] Test remakes and seasons
- [ ] Test anime/manga collisions
- [ ] Test movie/TV collisions

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
