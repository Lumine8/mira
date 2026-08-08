from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

QUESTION_SOURCES = {"self_authored", "inferred"}
QUESTION_STATUSES = {"open", "asked", "answered", "dropped"}


class Question(Base):
    """A question Mira is carrying — something she genuinely wonders about.

    Questions are the persistent form of her curiosity. Unlike wants (directions
    she keeps returning to), a question is a specific thing she wants to
    understand. She writes them herself during reflection, consolidation, or a
    digest (``self_authored``) or they are found written in her own record
    (``inferred``).

    ``importance`` is how much she cares about it right now; ``origin`` is the
    thing that raised it. Open questions resurface in her own context so she can
    ask them when a conversation makes them relevant. An un-revisited question
    slowly fades; one she keeps returning to grows. ``asked``/``answered`` mark
    the lifecycle; ``last_revisited`` tracks how long a question has simmered.
    """

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(24), default="self_authored")
    origin: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(16), default="open")
    related_conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    asked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_revisited: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
