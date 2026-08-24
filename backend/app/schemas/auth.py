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
    has_password: bool = False


class SignUpRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class SignInPasswordRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
