# MAL Conversational Assistant

Natural-language control layer for MyAnimeList. The backend is authoritative;
the LLM (later phases) is only an interpreter.

See `PROJECT_SPEC.md`, `AGENTS.md`, and `docs/behavior.md` before contributing.

## Requirements

- Python 3.12+
- Docker (optional, for compose)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
```

## Run locally

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

## Docker

```bash
docker compose up --build
```

## Quality checks

```bash
pytest
ruff check .
mypy backend/app
```

## Project docs

- `PROJECT_SPEC.md` — architecture and roadmap
- `AGENTS.md` — agent coding boundaries
- `IMPLEMENTATION_CHECKLIST.md` — phase tracker
- `docs/behavior.md` — behavioral contract
- `docs/oauth-setup.md` — register a MAL API app and connect OAuth
- `docs/mal-client.md` — raw MAL API client, retries, and manual reversible test
- `docs/domain.md` — application-domain models, validation, and lifecycle states

## Connect MAL (Phase 2)

1. Follow [`docs/oauth-setup.md`](docs/oauth-setup.md) to register a MAL API
   client and set `MAL_CLIENT_ID`, `MAL_CLIENT_SECRET`, `MAL_REDIRECT_URI`, and
   `TOKEN_ENCRYPTION_KEY`.
2. Run migrations and start the app.
3. Open `http://localhost:8000/auth/mal/start`, authorize, then check status:

```bash
curl -s http://localhost:8000/auth/mal/status
curl -s -X POST http://localhost:8000/auth/mal/disconnect
```

OAuth tokens are encrypted at rest and are never returned by the API.

## MAL client (Phase 3)

Typed authenticated MAL HTTP access lives in `backend/app/mal/`. See
[`docs/mal-client.md`](docs/mal-client.md).

## Domain model (Phase 4)

Typed application-domain models (requested changes, resolved media, list
states, plans, command lifecycle) live in `backend/app/domain/`. See
[`docs/domain.md`](docs/domain.md). MAL transport models stay in
`backend/app/mal/models.py`; converters are in
`backend/app/mal/domain_mapping.py`.

After connecting OAuth, you can run a reversible list update against a known
MAL ID (interactive confirmation; no deletes):

```bash
python scripts/mal_reversible_list_update.py \
  --media anime \
  --mal-id 9253 \
  --field score \
  --value 8
```
