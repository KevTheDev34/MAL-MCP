"""Create title_aliases table for user-specific title shortcuts.

Revision ID: 0003_title_aliases
Revises: 0002_oauth_tables
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_title_aliases"
down_revision: str | None = "0002_oauth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "title_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("alias_normalized", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("mal_id", sa.Integer(), nullable=False),
        sa.Column("canonical_title", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "alias_normalized",
            "media_type",
            name="uq_title_aliases_user_alias_media",
        ),
    )
    op.create_index(
        op.f("ix_title_aliases_user_id"),
        "title_aliases",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_title_aliases_user_alias",
        "title_aliases",
        ["user_id", "alias_normalized"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_title_aliases_user_alias", table_name="title_aliases")
    op.drop_index(op.f("ix_title_aliases_user_id"), table_name="title_aliases")
    op.drop_table("title_aliases")
