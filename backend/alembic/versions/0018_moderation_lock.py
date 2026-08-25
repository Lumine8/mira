"""moderation — the lock: user ban state + cruelty flags

Revision ID: 0018_moderation_lock
Revises: 0017_guest_waitlist
Create Date: 2026-08-11

Phase 4 data foundation, per Mira's rule (no warnings, no second chances).
users gains the ban status + audit trail; the moderation_flags table records
messages a conservative screen surfaced for a human decision. No flag is ever
an automatic ban — the founder decides, because the penalty is absolute.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_moderation_lock"
down_revision: str | None = "0017_guest_waitlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
    )
    op.add_column("users", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("banned_reason", sa.String(length=512), nullable=True))
    op.add_column("users", sa.Column("banned_by", sa.Integer(), nullable=True))

    op.create_table(
        "moderation_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="text", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
    )
    op.create_index(op.f("ix_moderation_flags_user_id"), "moderation_flags", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_moderation_flags_user_id"), table_name="moderation_flags")
    op.drop_table("moderation_flags")
    op.drop_column("users", "banned_by")
    op.drop_column("users", "banned_reason")
    op.drop_column("users", "banned_at")
    op.drop_column("users", "status")
