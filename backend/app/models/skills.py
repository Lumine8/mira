"""Telemetry for skills: a run is one execution, an evaluation is the record of
how that run proved itself. Files stay the source of truth; these tables only
carry the history so a skill can show it gets better over time."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.state import JSONB_PORTABLE


class SkillRun(Base):
    """One execution of a skill: what it was asked, what it produced, whether
    it went clean or failed."""

    __tablename__ = "skill_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    skill_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    task: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ran")  # ran | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillEvaluation(Base):
    """How one skill run proved itself: the dimension scores, the checks that
    ran, and any evidence notes. Appended after every evaluation so the history
    shows movement — the same skill, measured over versions."""

    __tablename__ = "skill_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("skill_runs.id"))
    skill_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    task: Mapped[str] = mapped_column(Text)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB_PORTABLE, default=dict)
    evidence: Mapped[list[Any]] = mapped_column(JSONB_PORTABLE, default=list)
    notes: Mapped[list[str]] = mapped_column(JSONB_PORTABLE, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillVersion(Base):
    """One edit to one of her skill files, pinned before and after so the change
    can be replayed, shown as a diff, and reverted. The files on disk stay the
    source of truth; this is the history that makes her growth reviewable."""

    __tablename__ = "skill_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    skill_id: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    kind: Mapped[str] = mapped_column(String(16), default="edit")  # edit | revert
    path: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text, default="")
    change_id: Mapped[int | None] = mapped_column(ForeignKey("pending_changes.id"), nullable=True)
    before_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())