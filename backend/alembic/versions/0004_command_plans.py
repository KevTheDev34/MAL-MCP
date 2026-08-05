"""Create command plan persistence tables for Phase 6.

Revision ID: 0004_command_plans
Revises: 0003_title_aliases
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_command_plans"
down_revision: str | None = "0003_title_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "command_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("normalized_request_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("cancel_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_command_runs_user_id"),
        "command_runs",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "change_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("command_run_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("canonical_plan_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["command_run_id"],
            ["command_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "command_run_id",
            "revision",
            name="uq_change_plans_run_revision",
        ),
    )
    op.create_index(
        op.f("ix_change_plans_command_run_id"),
        "change_plans",
        ["command_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_change_plans_user_id"),
        "change_plans",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "planned_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("change_plan_id", sa.String(length=36), nullable=False),
        sa.Column("apply_order", sa.Integer(), nullable=False),
        sa.Column("outcome_kind", sa.String(length=32), nullable=False),
        sa.Column("requested_change_json", sa.Text(), nullable=False),
        sa.Column("resolution_json", sa.Text(), nullable=True),
        sa.Column("mal_id", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=16), nullable=True),
        sa.Column("canonical_title", sa.String(length=512), nullable=True),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("is_noop", sa.Boolean(), nullable=False),
        sa.Column("source_titles_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("apply_result_kind", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["change_plan_id"],
            ["change_plans.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "change_plan_id",
            "apply_order",
            name="uq_planned_items_plan_order",
        ),
    )
    op.create_index(
        op.f("ix_planned_items_change_plan_id"),
        "planned_items",
        ["change_plan_id"],
        unique=False,
    )

    op.create_table(
        "application_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("planned_item_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=True),
        sa.Column("update_response_json", sa.Text(), nullable=True),
        sa.Column("verified_state_json", sa.Text(), nullable=True),
        sa.Column("observed_state_json", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message_redacted", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["planned_item_id"],
            ["planned_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "planned_item_id",
            "attempt_number",
            name="uq_application_attempts_item_number",
        ),
    )
    op.create_index(
        op.f("ix_application_attempts_planned_item_id"),
        "application_attempts",
        ["planned_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_application_attempts_planned_item_id"),
        table_name="application_attempts",
    )
    op.drop_table("application_attempts")
    op.drop_index(op.f("ix_planned_items_change_plan_id"), table_name="planned_items")
    op.drop_table("planned_items")
    op.drop_index(op.f("ix_change_plans_user_id"), table_name="change_plans")
    op.drop_index(op.f("ix_change_plans_command_run_id"), table_name="change_plans")
    op.drop_table("change_plans")
    op.drop_index(op.f("ix_command_runs_user_id"), table_name="command_runs")
    op.drop_table("command_runs")
