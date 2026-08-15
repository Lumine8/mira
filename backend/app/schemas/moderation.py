from datetime import datetime

from pydantic import BaseModel, Field


class ModerationFlagOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    user_role: str
    user_email: str | None = None
    conversation_id: int | None = None
    content: str
    kind: str
    reason: str
    status: str
    created_at: datetime


class ModerationUserOut(BaseModel):
    id: int
    name: str
    role: str
    email: str | None = None
    google: bool = False
    status: str
    banned_at: datetime | None = None
    banned_reason: str | None = None


class ModerationBanRequest(BaseModel):
    reason: str = Field(default="", max_length=512, description="Why the lock is being applied (the flag's own reason is the default)")


class ModerationBanOut(BaseModel):
    user: ModerationUserOut
    flag_id: int | None = None
