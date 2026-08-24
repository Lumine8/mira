from pydantic import BaseModel, EmailStr, Field

from app.models import PERSON_ROLE


class MagicLinkRequest(BaseModel):
    email: EmailStr = Field(description="The address to send the sign-in code to")


class MagicLinkVerify(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=10, description="The one-time code from the email")


class UserOut(BaseModel):
    id: int
    name: str
    role: str = PERSON_ROLE
    email: str | None = None
    google: bool = False


class AuthSuccess(BaseModel):
    access_token: str
    refresh_token: str
    user: UserOut
