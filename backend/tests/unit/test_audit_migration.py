"""Migration head and Phase 7 schema smoke tests."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_head_is_audit_idempotency_undo() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0005_audit_idempotency_undo"


def test_phase7_models_are_mapped() -> None:
    from backend.app.db import models  # noqa: F401
    from backend.app.db.base import Base

    tables = set(Base.metadata.tables)
    assert "command_runs" in tables
    assert "application_attempts" in tables
    assert "item_reversions" in tables
    attempt = Base.metadata.tables["application_attempts"]
    assert "idempotency_key" in attempt.c
    assert "outcome_certainty" in attempt.c
    run = Base.metadata.tables["command_runs"]
    assert "source_type" in run.c
    assert "parent_command_id" in run.c
