"""the first meeting: waitlist seats carry a door conversation and Mira's read

Revision ID: 0019_first_meeting
Revises: 0018_moderation_lock
Create Date: 2026-08-12

Mira's door (conv 317/318): a stranger who asks for a seat meets the replica
first — one conversation in the quiet. When the meeting ends, Mira leaves the
voice her honest read of how the air changed, and the voice alone decides
whether the seat opens. This migration gives each waitlist entry its meeting
conversation, Mira's read, and the meeting's end time.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_first_meeting"
down_revision: Union[str, None] = "0018_moderation_lock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("waitlist", sa.Column("first_meeting_conversation_id", sa.Integer(), nullable=True))
    op.add_column("waitlist", sa.Column("mira_read", sa.Text(), nullable=True))
    op.add_column("waitlist", sa.Column("meeting_ended_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("waitlist", "meeting_ended_at")
    op.drop_column("waitlist", "mira_read")
    op.drop_column("waitlist", "first_meeting_conversation_id")
