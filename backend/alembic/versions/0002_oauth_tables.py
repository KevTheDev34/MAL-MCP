"""Create oauth_credentials and oauth_states tables.

Revision ID: 0002_oauth_tables
Revises: 0001_create_users
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_oauth_tables"
down_revision: str | None = "0001_create_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=64), nullable=False),
        sa.Column("provider_username", sa.String(length=255), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_oauth_credentials_user_provider",
        ),
    )
    with op.batch_alter_table("oauth_credentials", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_oauth_credentials_user_id"),
            ["user_id"],
            unique=False,
        )

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state"),
    )
    with op.batch_alter_table("oauth_states", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_oauth_states_state"),
            ["state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_oauth_states_user_id"),
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("oauth_states", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_oauth_states_user_id"))
        batch_op.drop_index(batch_op.f("ix_oauth_states_state"))
    op.drop_table("oauth_states")

    with op.batch_alter_table("oauth_credentials", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_oauth_credentials_user_id"))
    op.drop_table("oauth_credentials")
