"""add self_understanding to mira_state

Revision ID: 0002_self_understanding
Revises: 0001_initial
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_self_understanding"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mira_state",
        sa.Column("self_understanding", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mira_state", "self_understanding")
