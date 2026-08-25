from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.state import JSONB_PORTABLE

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"

JOB_KINDS = ("mind_reflection", "mote_tick", "reminder_fire", "moderation_judge", "consolidation")


class BackgroundJob(Base):
    """A unit of background work claimed by exactly one process via
    SELECT FOR UPDATE SKIP LOCKED. Replaces process-global loops so multiple
    workers can safely share the load."""
    __tablename__ = "background_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB_PORTABLE, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=JOB_PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
