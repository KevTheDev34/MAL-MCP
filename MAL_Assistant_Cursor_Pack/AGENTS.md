# AGENTS.md

This repository contains a safety-conscious conversational assistant for MyAnimeList.

## Read first

Before making changes, read:

1. `PROJECT_SPEC.md`
2. `IMPLEMENTATION_CHECKLIST.md`
3. `docs/behavior.md`, when it exists

## Architectural boundary

The LLM is an interpreter. The backend is authoritative.

Never allow LLM code to:

- Send raw MAL HTTP requests
- Access MAL OAuth tokens
- Invent MAL IDs
- Bypass title resolution
- Bypass confirmation
- Apply stale plans
- Claim success without read-after-write verification

All writes must follow:

```text
resolve -> read current state -> plan -> preview -> confirm -> apply -> verify -> audit
```

## Implementation rules

- Work on one roadmap phase at a time.
- Do not implement future phases unless required by the current phase.
- Keep route handlers thin.
- Put business logic in services.
- Put MAL HTTP logic only in the MAL client.
- Put persistence logic in repositories.
- Use typed Pydantic models at boundaries.
- Add tests with each behavior.
- Use domain-specific exceptions.
- Redact credentials and tokens from logs.
- Never commit `.env`.
- Preserve idempotency and auditability.
- Run formatter, linter, type checker, and tests before considering a task complete.

## Preferred stack

- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- SQLite
- httpx
- pytest
- ruff
- mypy

## Definition of done

A change is complete only when:

- The feature is documented.
- Tests cover happy and failure paths.
- Validation is implemented.
- Errors are typed and user-safe.
- No secrets appear in logs.
- The implementation follows the current project phase.
- All checks pass.

## Commands

Expected commands after project scaffolding:

```bash
docker compose up --build
pytest
ruff check .
mypy backend/app
```

## Change discipline

Prefer small, reviewable changes.

Before editing:

1. Summarize the current relevant architecture.
2. State the files to be changed.
3. State assumptions.

After editing:

1. Summarize the implementation.
2. List tests added.
3. Report commands run and results.
4. Note remaining risks or follow-up tasks.
