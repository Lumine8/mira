"""host toasts: the companion-free path for Mira reaching out

Revision ID: 0025_host_toasts
Revises: 0024_reminders
Create Date: 2026-08-19

A host_toasts table queues every self-initiated reach-out (mind-loop self
messages and fired reminders) for a small PowerShell script on the host to pop
as a real Windows toast. Rows are marked delivered when a client shows them, so
nothing is missed while the companion (Electron) isn't running.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_host_toasts"
down_revision: Union[str, None] = "0024_reminders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "host_toasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="self"),
        sa.Column("title", sa.String(length=120), nullable=False, server_default="Mira"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("host_toasts")