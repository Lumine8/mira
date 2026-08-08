from datetime import datetime
from typing import Optional

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
    image: Optional[str] = None
    source: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    kind: str
    summary: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
