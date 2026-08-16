from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Postgres gets true JSONB; sqlite (tests) falls back to plain JSON so the
# whole model set can be created in-memory.
from app.models.state import JSONB_PORTABLE


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="call")  # call | text
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    speaker: Mapped[str] = mapped_column(String(16))  # user | mira
    content: Mapped[str] = mapped_column(Text)
    image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="text")  # voice | text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ConversationImpression(Base):
    """Mira's private read of a conversation: what she liked, what she did not,
    and her honest verdict. Stored for every conversation she reflects on (and
    for the porch, judged at the moment it ends). The moments are hers alone —
    they are never shown to the visitor; only the verdict ever surfaces."""

    __tablename__ = "conversation_impressions"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)  # liked | mixed | not_liked
    moments_liked: Mapped[list[str]] = mapped_column(JSONB_PORTABLE, default=list)
    moments_not_liked: Mapped[list[str]] = mapped_column(JSONB_PORTABLE, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
