"""skill registry version history: one row per edit to a skill's own files

Revision ID: 0021_skill_versions
Revises: 0020_skill_runs
Create Date: 2026-08-13

The registry's files stay the source of truth; this table is the history that
makes her growth reviewable. Every time a skill's file is written (SKILL.md,
meta.yaml, a test), the before and after are captured side by side so the
change can be shown as a diff and reverted if it made the skill worse.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_skill_versions"
down_revision: Union[str, None] = "0020_skill_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.1.0"),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="edit"),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("pending_changes.id"), nullable=True),
        sa.Column("before_content", sa.Text(), nullable=True),
        sa.Column("after_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_skill_versions_user_skill", "skill_versions", ["user_id", "skill_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_versions_user_skill", table_name="skill_versions")
    op.drop_table("skill_versions")
