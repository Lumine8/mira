"""skill registry telemetry: runs and evaluations

Revision ID: 0020_skill_runs
Revises: 0019_first_meeting
Create Date: 2026-08-13

The registry's files are the source of truth; these tables only carry the
history so a skill can prove itself over time — one row per run, one per
evaluation, with the scores and evidence the evaluator produced.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_skill_runs"
down_revision: Union[str, None] = "0019_first_meeting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.1.0"),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ran"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "skill_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("skill_runs.id"), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.1.0"),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_skill_runs_user_skill", "skill_runs", ["user_id", "skill_id"])
    op.create_index("ix_skill_evaluations_run", "skill_evaluations", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_evaluations_run", table_name="skill_evaluations")
    op.drop_index("ix_skill_runs_user_skill", table_name="skill_runs")
    op.drop_table("skill_evaluations")
    op.drop_table("skill_runs")