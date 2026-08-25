"""the held calendar: reminders, tasks, and events

Revision ID: 0024_reminders
Revises: 0023_meeting_outcome
Create Date: 2026-08-19

A single reminders table holds everything Mira keeps for the voice — one-shot
reminders, open tasks (no due moment), and calendar events. The reminders loop
fires whatever is due, broadcasts it on the live hub (so the HUD reads it
aloud), and marks it notified so it never repeats.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_reminders"
down_revision: str | None = "0023_meeting_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="reminder"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("reminders")
