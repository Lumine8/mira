"""real identity: email + google_sub on users; sessions, magic links, oauth states

Revision ID: 0016_real_identity
Revises: 0015_user_scoping
Create Date: 2026-08-11

Phase 2 data foundation. The shared-token founder seam gains a real-identity
layer on top: authenticated users carry an email (magic-link handle) and/or a
google_sub (stable Google id), and three tables hold the handshake artifacts —
sessions (opaque bearer tokens, hashed), magic_links (one-time email codes,
hashed) and oauth_states (Google PKCE handshakes). Nothing here changes the
founder's world; it only adds the rows real auth needs.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_real_identity"
down_revision: str | None = "0015_user_scoping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("users", sa.Column("google_sub", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user_id_users"),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_unique_constraint("uq_sessions_token_hash", "sessions", ["token_hash"])

    op.create_table(
        "magic_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_magic_links_email"), "magic_links", ["email"])
    op.create_unique_constraint("uq_magic_links_code_hash", "magic_links", ["code_hash"])

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_oauth_states_state", "oauth_states", ["state"])


def downgrade() -> None:
    op.drop_table("oauth_states")
    op.drop_table("magic_links")
    op.drop_table("sessions")
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "email")
