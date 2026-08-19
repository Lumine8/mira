from datetime import datetime

from pydantic import BaseModel, Field


class ReminderIn(BaseModel):
    """Something for Mira to keep. kind is reminder (one-shot), task (open
    loop, due_at optional), or event (a fixed moment in the calendar)."""

    title: str = Field(min_length=1, max_length=500)
    kind: str = Field(default="reminder", max_length=16)
    due_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)


class ReminderOut(BaseModel):
    id: int
    kind: str
    title: str
    note: str | None = None
    due_at: datetime | None = None
    done: bool
    notified: bool
    created_at: datetime