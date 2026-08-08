"""perceived_events + mira_state reflection fields

Revision ID: 0004_mind_loop
Revises: 0003_embedding_dim_768
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_mind_loop"
down_revision: Union[str, None] = "0003_embedding_dim_768"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "perceived_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("consumed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("mira_state", sa.Column("pending_message", sa.Text(), nullable=True))
    op.add_column(
        "mira_state",
        sa.Column("last_reflection_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mira_state", "last_reflection_at")
    op.drop_column("mira_state", "pending_message")
    op.drop_table("perceived_events")
