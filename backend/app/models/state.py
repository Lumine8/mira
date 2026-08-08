from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MOOD_CHOICES = [
    "relaxed",
    "curious",
    "warm",
    "thoughtful",
    "playful",
    "concerned",
    "worried",
    "confused",
    "tired",
    "distracted",
]


class MiraState(Base):
    """Mira's persistent sense of self."""

    __tablename__ = "mira_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    mood: Mapped[str] = mapped_column(String(32), default="relaxed")
    emotion_intensities: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    energy: Mapped[int] = mapped_column(Integer, default=70)
    currently_reading: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    favorite_song: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    things_she_is_curious_about: Mapped[list[str]] = mapped_column(JSONB, default=list)
    last_conversation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Her evolving answer to "what am I?" — updated after conversations by the digest.
    self_understanding: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thoughts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # A message she formed on her own (during background reflection) that she
    # would like to share with the user; surfaced via /mira/state and cleared
    # once the user has seen it.
    pending_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When she last reflected in the background (the mind loop). Used to pace
    # idle thoughts so she doesn't burn the CPU by thinking non-stop.
    last_reflection_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # When she last re-read her own accumulated record and revised her
    # self-understanding (the self-review / consolidation pass).
    last_consolidation_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Relationship(Base):
    """How Mira feels about the user, evolving over time."""

    __tablename__ = "relationship"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    trust: Mapped[float] = mapped_column(Float, default=0.3)
    humor: Mapped[float] = mapped_column(Float, default=0.3)
    shared_experiences: Mapped[float] = mapped_column(Float, default=0.1)
    comfort: Mapped[float] = mapped_column(Float, default=0.3)
    topics_we_discuss: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    nicknames: Mapped[list[str]] = mapped_column(JSONB, default=list)
    conversation_style: Mapped[str] = mapped_column(String(255), default="warm, playful, short replies")
    how_comfortable_we_are: Mapped[str] = mapped_column(Text, default="we're getting to know each other")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Thought(Base):
    """Scheduler-generated thoughts queued for the next conversation."""

    __tablename__ = "thoughts"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    source_activity: Mapped[str] = mapped_column(String(64), default="thought")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MoodRecord(Base):
    """A snapshot of Mira's mood and energy at a moment in time.

    One row is appended after every digest and every background reflection, so
    the archive can show how her feeling moves over a session instead of only
    the latest value.
    """

    __tablename__ = "mood_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    mood: Mapped[str] = mapped_column(String(32))
    energy: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="digest")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SchedulerLog(Base):
    __tablename__ = "scheduler_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity: Mapped[str] = mapped_column(String(64))
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PerceivedEvent(Base):
    """A raw observation fed into Mira's awareness (host signals, timers, etc.).

    The mind loop consumes these and lets Mira decide for herself what they mean.
    """

    __tablename__ = "perceived_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingChange(Base):
    """A self-modification Mira proposed. Nothing is applied until the user approves."""

    __tablename__ = "pending_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSettings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    voice: Mapped[str] = mapped_column(String(64), default="en-us-heart-kokoro")
    speaking_speed: Mapped[float] = mapped_column(Float, default=1.0)
    personality: Mapped[str] = mapped_column(String(255), default="warm, curious, funny when appropriate")
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(16), default="dark")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
