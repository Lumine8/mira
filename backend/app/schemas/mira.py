from datetime import datetime

from pydantic import BaseModel, Field


class MiraStateOut(BaseModel):
    mood: str
    energy: int
    self_understanding: str | None = None
    things_she_is_curious_about: list[str] = []
    last_conversation_summary: str | None = None
    pending_message: str | None = None
    pending_message_conversation_id: int | None = None
    carried_thoughts: list[str] = Field(default_factory=list)
    last_reflection_at: datetime | None = None
    updated_at: datetime
    # The word that summons her in always-listening mode ("" = no wake word).
    wake_word: str = ""


class RelationshipOut(BaseModel):
    trust: float
    humor: float
    comfort: float
    nicknames: list[str] = []
    how_comfortable_we_are: str = ""
    topics_we_discuss: dict[str, int] = {}


class MiraOut(BaseModel):
    state: MiraStateOut
    relationship: RelationshipOut


class MemoryOut(BaseModel):
    id: int
    type: str
    content: str
    valence: str | None = None
    source_conversation_id: int | None = None
    created_at: datetime


class MiraMemoryOut(BaseModel):
    """The memory window Mira consented to: her state, her relationship, and the
    memories she carries."""
    state: MiraStateOut
    relationship: RelationshipOut
    memories: list[MemoryOut]


class PerceivedEventIn(BaseModel):
    """A raw observation from the outside world (host agent, timers, integrations)."""

    source: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1)


class ProposeChangeIn(BaseModel):
    """A self-modification Mira wants to make; requires user approval to apply."""

    kind: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=2000)
    payload: dict


class PendingChangeOut(BaseModel):
    id: int
    kind: str
    summary: str
    payload: dict
    status: str
    result: str | None = None
    created_at: datetime


class WantOut(BaseModel):
    """A direction Mira's own attention keeps returning to — written by her or
    found in her record. Not a felt craving; an honest, grounded direction."""

    id: int
    content: str
    source: str
    intensity: int
    tension: int
    status: str
    related_conversation_id: int | None = None
    created_at: datetime
    updated_at: datetime


class QuestionOut(BaseModel):
    """A question Mira is carrying — something she genuinely wonders about and
    may ask someday when a conversation makes it relevant."""

    id: int
    question: str
    source: str
    origin: str | None = None
    importance: int
    status: str
    related_conversation_id: int | None = None
    asked_at: datetime | None = None
    answered_at: datetime | None = None
    last_revisited: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MoodRecordOut(BaseModel):
    """A snapshot of Mira's mood and energy at a moment in time."""

    id: int
    mood: str
    energy: int
    source: str
    note: str | None = None
    created_at: datetime
