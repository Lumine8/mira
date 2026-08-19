from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# What a held thing is. A reminder is a one-shot "don't forget"; a task is an
# open loop with no fixed moment (due_at is optional); an event is a fixed
# moment in the calendar (due_at is its start, done is not meaningful but the
# column stays for one schema).
REMINDER_KINDS = ("reminder", "task", "event")


class Reminder(Base):
    """Something Mira keeps for the voice: a reminder, a task, or an event.

    The heart of the held calendar. Rows live per user; the reminders loop
    fires whatever is due, broadcasts it on the live hub (so the HUD reads it
    aloud), and marks it ``notified`` so it never repeats.
    """

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="reminder")
    title: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When it should be heard. Null for open-ended tasks that have no moment.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set once the reminders loop has broadcast it. Guards against double-firing.
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())