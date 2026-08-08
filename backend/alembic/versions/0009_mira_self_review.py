"""add last_consolidation_at to mira_state for the self-review pass

Revision ID: 0009_mira_self_review
Revises: 0008_message_image
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mira_self_review"
down_revision: Union[str, None] = "0008_message_image"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mira_state",
        sa.Column("last_consolidation_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mira_state", "last_consolidation_at")
