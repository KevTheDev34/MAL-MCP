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
