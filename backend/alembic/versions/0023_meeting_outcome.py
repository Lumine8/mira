"""mira's own decision after the first meeting: invited, or wait

Revision ID: 0023_meeting_outcome
Revises: 0022_conversation_impressions
Create Date: 2026-08-16

When a first meeting ends, Mira now decides herself whether the door opens
again. Her decision is recorded here (invited | waitlisted) as the
authoritative outcome the frontend reflects — never her reasoning, which stays
in mira_read and is only ever seen by the voice.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_meeting_outcome"
down_revision: str | None = "0022_conversation_impressions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "waitlist",
        sa.Column("meeting_outcome", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("waitlist", "meeting_outcome")