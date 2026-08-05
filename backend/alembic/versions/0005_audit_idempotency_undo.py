"""Add audit, idempotency, and undo persistence for Phase 7.

Revision ID: 0005_audit_idempotency_undo
Revises: 0004_command_plans
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_audit_idempotency_undo"
down_revision: str | None = "0004_command_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("command_runs") as batch:
        batch.add_column(
            sa.Column(
                "source_type",
                sa.String(length=32),
                nullable=False,
                server_default="api",
            )
        )
        batch.add_column(
            sa.Column("parent_command_id", sa.String(length=36), nullable=True)
        )
        batch.create_foreign_key(
            "fk_command_runs_parent_command_id",
            "command_runs",
            ["parent_command_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_command_runs_parent_command_id",
            ["parent_command_id"],
            unique=False,
        )
        batch.create_index(
            "ix_command_runs_user_id_created_at",
            ["user_id", "created_at"],
            unique=False,
        )

    with op.batch_alter_table("planned_items") as batch:
        batch.add_column(
            sa.Column(
                "reversion_status",
                sa.String(length=32),
                nullable=False,
                server_default="none",
            )
        )

    with op.batch_alter_table("application_attempts") as batch:
        batch.add_column(
            sa.Column("idempotency_key", sa.String(length=191), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "outcome_certainty",
                sa.String(length=32),
                nullable=False,
                server_default="certain",
            )
        )
        batch.add_column(
            sa.Column("field_mismatches_json", sa.Text(), nullable=True)
        )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT a.id, a.state, a.planned_item_id, p.change_plan_id,
                   cp.user_id, cp.id AS plan_id, cp.revision, cp.plan_hash
            FROM application_attempts a
            JOIN planned_items p ON p.id = a.planned_item_id
            JOIN change_plans cp ON cp.id = p.change_plan_id
            """
        )
    ).fetchall()
    for row in rows:
        attempt_id, state, item_id, _plan_fk, user_id, plan_id, revision, plan_hash = (
            row
        )
        key = f"apply:{user_id}:{plan_id}:{revision}:{item_id}:{plan_hash}"
        certainty = "uncertain" if state in ("writing", "written_unverified") else "certain"
        conn.execute(
            sa.text(
                """
                UPDATE application_attempts
                SET idempotency_key = :key, outcome_certainty = :certainty
                WHERE id = :id
                """
            ),
            {"key": key, "certainty": certainty, "id": attempt_id},
        )

    # Any leftover rows without joins get a legacy key.
    conn.execute(
        sa.text(
            """
            UPDATE application_attempts
            SET idempotency_key = 'legacy:' || id
            WHERE idempotency_key IS NULL
            """
        )
    )

    with op.batch_alter_table("application_attempts") as batch:
        batch.alter_column(
            "idempotency_key",
            existing_type=sa.String(length=191),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_application_attempts_idempotency_key",
            ["idempotency_key"],
        )

    op.create_table(
        "item_reversions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("original_planned_item_id", sa.String(length=36), nullable=False),
        sa.Column("original_command_run_id", sa.String(length=36), nullable=False),
        sa.Column("reverse_command_run_id", sa.String(length=36), nullable=False),
        sa.Column("reverse_planned_item_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("conflict_json", sa.Text(), nullable=True),
        sa.Column("fully_restored", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["original_planned_item_id"],
            ["planned_items.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_command_run_id"],
            ["command_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reverse_command_run_id"],
            ["command_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reverse_planned_item_id"],
            ["planned_items.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "original_planned_item_id",
            "reverse_planned_item_id",
            name="uq_item_reversions_original_reverse",
        ),
    )
    op.create_index(
        op.f("ix_item_reversions_user_id"),
        "item_reversions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_item_reversions_original_planned_item_id"),
        "item_reversions",
        ["original_planned_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_item_reversions_original_command_run_id"),
        "item_reversions",
        ["original_command_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_item_reversions_reverse_command_run_id"),
        "item_reversions",
        ["reverse_command_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_item_reversions_reverse_planned_item_id"),
        "item_reversions",
        ["reverse_planned_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_item_reversions_reverse_planned_item_id"),
        table_name="item_reversions",
    )
    op.drop_index(
        op.f("ix_item_reversions_reverse_command_run_id"),
        table_name="item_reversions",
    )
    op.drop_index(
        op.f("ix_item_reversions_original_command_run_id"),
        table_name="item_reversions",
    )
    op.drop_index(
        op.f("ix_item_reversions_original_planned_item_id"),
        table_name="item_reversions",
    )
    op.drop_index(op.f("ix_item_reversions_user_id"), table_name="item_reversions")
    op.drop_table("item_reversions")

    with op.batch_alter_table("application_attempts") as batch:
        batch.drop_constraint(
            "uq_application_attempts_idempotency_key",
            type_="unique",
        )
        batch.drop_column("field_mismatches_json")
        batch.drop_column("outcome_certainty")
        batch.drop_column("idempotency_key")

    with op.batch_alter_table("planned_items") as batch:
        batch.drop_column("reversion_status")

    with op.batch_alter_table("command_runs") as batch:
        batch.drop_index("ix_command_runs_user_id_created_at")
        batch.drop_index("ix_command_runs_parent_command_id")
        batch.drop_constraint("fk_command_runs_parent_command_id", type_="foreignkey")
        batch.drop_column("parent_command_id")
        batch.drop_column("source_type")
