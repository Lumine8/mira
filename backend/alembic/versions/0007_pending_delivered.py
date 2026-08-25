"""add delivered flag to pending_changes so approved browse results can reach Mira once

Revision ID: 0007_pending_delivered
Revises: 0006_browse_result
Create Date: 2026-08-03

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_pending_delivered"
down_revision: str | None = "0006_browse_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pending_changes",
        sa.Column(
            "delivered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pending_changes", "delivered")
