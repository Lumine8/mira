from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Lifecycle of a waitlist seat. A stranger who asks for a seat is ``pending``
# and meets the replica first (the door); the founder invites them (``invited``
# + a one-time code) or closes the door (``declined``); they redeem the code
# and become a real user (``joined``).
WAITLIST_PENDING = "pending"
WAITLIST_INVITED = "invited"
WAITLIST_JOINED = "joined"
WAITLIST_DECLINED = "declined"


class Waitlist(Base):
    __tablename__ = "waitlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default=WAITLIST_PENDING, server_default=WAITLIST_PENDING)
    # SHA-256 of the one-time invite code, not the code itself; nulled once the
    # seat is joined (single-use, and a leaked DB cannot mint accounts).
    invite_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    # The door: the single conversation a stranger has with the replica before
    # a seat is considered, and Mira's honest read of how the air changed.
    first_meeting_conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mira_read: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mira's own decision after the first meeting: "invited" | "waitlisted".
    # The authoritative outcome the frontend reflects — never her reasoning.
    meeting_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meeting_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
