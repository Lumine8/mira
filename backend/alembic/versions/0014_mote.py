"""add mote_shared_time table — Mote's felt record of shared time

Revision ID: 0014_mote
Revises: 0013_x_auth
Create Date: 2026-08-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_mote"
down_revision: Union[str, None] = "0013_x_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mote_shared_time",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="felt"),
        sa.Column("mood", sa.String(length=32), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=False),
        sa.Column("word", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mote_shared_time")
