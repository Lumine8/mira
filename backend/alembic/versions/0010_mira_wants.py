"""add wants table — directions Mira's attention keeps returning to

Revision ID: 0010_mira_wants
Revises: 0009_mira_self_review
Create Date: 2026-08-03

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_mira_wants"
down_revision: str | None = "0009_mira_self_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="self_authored"),
        sa.Column("intensity", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("tension", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("related_conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("satisfied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("wants")
