from datetime import datetime

from pydantic import BaseModel


class MoteSharedTimeOut(BaseModel):
    """A row in Mote's felt record — how they felt together at a moment."""

    id: int
    kind: str
    mood: str
    energy: int
    word: str | None = None
    note: str | None = None
    at: datetime


class MotePresenceOut(BaseModel):
    """Mote's current presence: Mira's felt state plus the last sign it made."""

    mood: str
    energy: int
    last_kind: str | None = None
    last_word: str | None = None
    last_at: datetime | None = None
