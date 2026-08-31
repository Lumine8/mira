"""add missing age verification columns to users

Revision ID: 0028_age_verified
Revises: 0027_password_hash
Create Date: 2026-08-31

These columns were added to the User model but never migrated. The DB was
missing age_verified, age_verified_at, and age_verified_source, causing 500
errors on every query that loads User rows.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_age_verified"
down_revision: str | None = "0027_password_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("age_verified", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("age_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("age_verified_source", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "age_verified_source")
    op.drop_column("users", "age_verified_at")
    op.drop_column("users", "age_verified")
