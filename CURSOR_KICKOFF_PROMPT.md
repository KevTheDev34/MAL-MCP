# Cursor Kickoff Prompt

Use this prompt in Cursor after placing `PROJECT_SPEC.md`, `AGENTS.md`, and
`IMPLEMENTATION_CHECKLIST.md` in the repository root.

---

You are helping build the MAL Conversational Assistant described in
`PROJECT_SPEC.md`.

Before editing anything:

1. Read `PROJECT_SPEC.md`.
2. Read `AGENTS.md`.
3. Read `IMPLEMENTATION_CHECKLIST.md`.
4. Summarize the architecture and the boundaries that must not be violated.
5. Inspect the existing repository and report what already exists.
6. State any assumptions.

Implement only **Phase 0 and Phase 1**.

Phase 0:

- Create `docs/behavior.md`.
- Define supported intents, status mappings, ambiguity handling, confirmation
  requirements, bulk failure behavior, no-op behavior, overwrite warnings, and
  undo-conflict behavior.
- Include concrete conversational examples and expected structured behavior.

Phase 1:

- Scaffold a Python 3.12 FastAPI project.
- Add Pydantic settings.
- Add SQLAlchemy and Alembic.
- Use SQLite initially.
- Add structured logging.
- Add a health endpoint at `GET /health`.
- The health endpoint must verify database connectivity.
- Add pytest, ruff, and mypy.
- Add a Dockerfile and `docker-compose.yml`.
- Add `.env.example`.
- Add a concise README with development commands.
- Add an initial migration.
- Add tests for the health endpoint and database connectivity.
- Add a simple CI workflow that runs tests, lint, and type checking.

Constraints:

- Do not implement MAL OAuth yet.
- Do not implement MAL API calls yet.
- Do not implement LLM integration yet.
- Do not add React.
- Do not add speculative abstractions for future phases unless needed by Phase 1.
- Keep route handlers thin.
- Use type annotations throughout.
- Do not commit secrets.
- Ensure logs cannot accidentally dump environment variables.

Acceptance criteria:

```bash
docker compose up --build
```

starts the application.

```bash
curl http://localhost:8000/health
```

returns a successful JSON response that includes application and database health.

These commands must pass:

```bash
pytest
ruff check .
mypy backend/app
```

At the end:

1. Summarize the files created or changed.
2. Explain the main implementation decisions.
3. List every command run and whether it passed.
4. Identify any incomplete acceptance criterion.
5. Update `IMPLEMENTATION_CHECKLIST.md`.
6. Do not begin Phase 2.
