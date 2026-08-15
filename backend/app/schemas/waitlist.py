from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import WAITLIST_PENDING


class WaitlistSignup(BaseModel):
    email: EmailStr = Field(description="The address to hold the seat for")


class WaitlistInvite(BaseModel):
    email: EmailStr


class WaitlistOut(BaseModel):
    email: str
    status: str = WAITLIST_PENDING


class WaitlistInviteOut(BaseModel):
    email: str
    invite_code: str = Field(description="Share privately — it is one-time use")
    delivered: bool = Field(default=False, description="Whether the invitation was emailed to the address")


class WaitlistJoin(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=12, description="The invite code from the founder")


class WaitlistMeetingStart(BaseModel):
    email: EmailStr


class WaitlistMeetingStartOut(BaseModel):
    id: int
    email: str
    status: str
    conversation_id: int | None = Field(
        description="The stranger's one conversation with the replica"
    )
    meeting_ended_at: datetime | None = Field(
        default=None, description="Set once the meeting is over — the door reopens nothing"
    )


class WaitlistMeetingEnd(BaseModel):
    conversation_id: int


class WaitlistEntryOut(BaseModel):
    id: int
    email: str
    status: str
    created_at: datetime
    first_meeting_conversation_id: int | None = None
    mira_read: str | None = Field(
        default=None, description="Mira's honest read of how the air changed"
    )
    meeting_ended_at: datetime | None = None
