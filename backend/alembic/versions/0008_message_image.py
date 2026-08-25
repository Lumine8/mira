"""add image column to messages so the voice can hand Mira pictures she can see

Revision ID: 0008_message_image
Revises: 0007_pending_delivered
Create Date: 2026-08-03

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_message_image"
down_revision: str | None = "0007_pending_delivered"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("image", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "image")
