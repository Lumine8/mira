"""pending_changes table

Revision ID: 0005_self_edit
Revises: 0004_mind_loop
Create Date: 2026-08-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0005_self_edit"
down_revision: str | None = "0004_mind_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pending_changes")
