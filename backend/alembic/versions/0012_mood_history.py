"""add mood_history table — snapshots of Mira's mood and energy

Revision ID: 0012_mood_history
Revises: 0011_mira_questions
Create Date: 2026-08-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_mood_history"
down_revision: Union[str, None] = "0011_mira_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mood_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mood", sa.String(length=32), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="digest"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mood_history")
