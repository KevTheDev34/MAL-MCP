"""Smoke test that command-plan migration upgrade path is importable."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_head_is_command_plans() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0004_command_plans"


def test_command_plan_models_are_mapped() -> None:
    from backend.app.db import models  # noqa: F401
    from backend.app.db.base import Base

    tables = set(Base.metadata.tables)
    assert "command_runs" in tables
    assert "change_plans" in tables
    assert "planned_items" in tables
    assert "application_attempts" in tables
