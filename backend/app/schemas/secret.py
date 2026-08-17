from pydantic import BaseModel


class SecretDoorIn(BaseModel):
    phrase: str = ""


class SecretDoorOut(BaseModel):
    token: str
    expires_in: int


class SecretRoomOut(BaseModel):
    opening: str
    presence: str
    truths: list[str]
