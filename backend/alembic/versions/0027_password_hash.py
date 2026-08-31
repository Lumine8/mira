"""password hash column on users

Revision ID: 0027_password_hash
Revises: 0026_audit_log
Create Date: 2026-08-31

Adds the password_hash column to the users table for password-based
authentication (bcrypt hashes). This column was present in the model but
never migrated to the database.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_password_hash"
down_revision: str | None = "0026_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
