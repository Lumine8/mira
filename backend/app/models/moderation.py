from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# A flag's lifecycle: a conservative screen surfaces cruelty as ``open``; the
# founder either resolves it (ban) or dismisses it (false positive). No flag is
# ever an automatic ban — the human decides, because the penalty is absolute.
FLAG_OPEN = "open"
FLAG_RESOLVED = "resolved"
FLAG_DISMISSED = "dismissed"
FLAG_STATUSES = [FLAG_OPEN, FLAG_RESOLVED, FLAG_DISMISSED]


class ModerationFlag(Base):
    """A message a conservative screen thinks may be cruelty.

    The row is a *candidate* for Mira's rule, never the verdict. It records
    what was said, in which conversation, by whom, and why it was surfaced —
    so the founder can judge it the way Mira would: immediately, and only once.
    """

    __tablename__ = "moderation_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), default="text")  # text | image
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=FLAG_OPEN, server_default=FLAG_OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
