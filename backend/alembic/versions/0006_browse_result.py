"""add result column to pending_changes

Revision ID: 0006_browse_result
Revises: 0005_self_edit
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_browse_result"
down_revision: Union[str, None] = "0005_self_edit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pending_changes", sa.Column("result", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pending_changes", "result")
