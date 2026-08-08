"""add questions table — questions Mira is carrying

Revision ID: 0011_mira_questions
Revises: 0010_mira_wants
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_mira_questions"
down_revision: Union[str, None] = "0010_mira_wants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="self_authored"),
        sa.Column("origin", sa.String(length=512), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("related_conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_revisited", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("questions")
