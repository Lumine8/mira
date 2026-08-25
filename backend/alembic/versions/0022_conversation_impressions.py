"""mira's private read of each conversation: what she liked, what she did not

Revision ID: 0022_conversation_impressions
Revises: 0021_skill_versions
Create Date: 2026-08-16

Every conversation she reflects on (and the porch, judged the moment it ends)
gets an impression: her honest verdict and the specific moments she liked and
did not like. The moments stay hers alone — nothing but the verdict ever
surfaces to a visitor.

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0022_conversation_impressions"
down_revision: str | None = "0021_skill_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_impressions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("moments_liked", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("moments_not_liked", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversation_impressions_conversation", "conversation_impressions", ["conversation_id"])
    op.create_index("ix_conversation_impressions_user", "conversation_impressions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_impressions_user", table_name="conversation_impressions")
    op.drop_index("ix_conversation_impressions_conversation", table_name="conversation_impressions")
    op.drop_table("conversation_impressions")