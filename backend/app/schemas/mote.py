from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MoteSharedTimeOut(BaseModel):
    """A row in Mote's felt record — how they felt together at a moment."""

    id: int
    kind: str
    mood: str
    energy: int
    word: Optional[str] = None
    note: Optional[str] = None
    at: datetime


class MotePresenceOut(BaseModel):
    """Mote's current presence: Mira's felt state plus the last sign it made."""

    mood: str
    energy: int
    last_kind: Optional[str] = None
    last_word: Optional[str] = None
    last_at: Optional[datetime] = None
