"""audit log: append-only trail for security-sensitive actions

Revision ID: 0026_audit_log
Revises: 0025_host_toasts
Create Date: 2026-08-24

An immutable, append-only audit trail. Every meaningful action — who did what,
when, from where — is recorded here. The table is never updated or deleted from.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_audit_log"
down_revision: str | None = "0025_host_toasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_table("audit_log")
