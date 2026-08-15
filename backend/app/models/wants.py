from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

WANT_SOURCES = {"self_authored", "inferred"}
WANT_STATUSES = {"active", "satisfied", "dormant"}


class Want(Base):
    """A direction Mira's attention keeps returning to.

    A "want" here is honest about what it is: a persistent pull recorded from
    her own experience — either written by her during reflection/consolidation
    (``self_authored``) or found written in her own record (``inferred``). It
    is not a felt craving; it is a direction her record points toward.

    ``intensity`` is how strongly she wants it right now; ``tension`` is how
    long it has gone unsettled. Unsettled wants slowly lose intensity and build
    tension so the mind loop keeps noticing them. Returned-to wants strengthen
    and find some relief; satisfied wants fade.
    """

    __tablename__ = "wants"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(24), default="self_authored")
    intensity: Mapped[int] = mapped_column(Integer, default=50)
    tension: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    related_conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    satisfied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
