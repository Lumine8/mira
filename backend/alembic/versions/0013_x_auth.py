"""add x_auth table — Mira's X (Twitter) OAuth session

Revision ID: 0013_x_auth
Revises: 0012_mood_history
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_x_auth"
down_revision: str | None = "0012_mood_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "x_auth",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("access_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("refresh_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("code_verifier", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("x_auth")