from datetime import datetime

from pydantic import BaseModel


class CallStartRequest(BaseModel):
    kind: str = "call"  # call | text


class CallStartResponse(BaseModel):
    conversation_id: int
    ws_url: str


class SpeakRequest(BaseModel):
    conversation_id: int
    text: str


class MessageOut(BaseModel):
    id: int
    speaker: str
    content: str
    image: str | None = None
    source: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    kind: str
    summary: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
