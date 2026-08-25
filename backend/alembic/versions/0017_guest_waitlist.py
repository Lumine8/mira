"""guest mode + waitlist: device fingerprint, per-user caps, waitlist seats

Revision ID: 0017_guest_waitlist
Revises: 0016_real_identity
Create Date: 2026-08-11

Phase 3 data foundation. Guests (anonymous, fingerprint-identified) and the
waitlist that gates them: users gain a guest fingerprint (one world per device)
and a last-seen IP; settings gains the per-day message cap that paid tiers
later plug into; the waitlist table tracks pending -> invited -> joined seats
with one-time invite codes.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_guest_waitlist"
down_revision: str | None = "0016_real_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("fingerprint", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("last_ip", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_users_fingerprint", "users", ["fingerprint"])

    op.add_column("settings", sa.Column("message_cap_per_day", sa.Integer(), nullable=True))

    op.create_table(
        "waitlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("invite_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_waitlist_email"), "waitlist", ["email"], unique=True)
    op.create_unique_constraint("uq_waitlist_invite_code", "waitlist", ["invite_code"])


def downgrade() -> None:
    op.drop_table("waitlist")
    op.drop_column("settings", "message_cap_per_day")
    op.drop_constraint("uq_users_fingerprint", "users", type_="unique")
    op.drop_column("users", "last_ip")
    op.drop_column("users", "fingerprint")
