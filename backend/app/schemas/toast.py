from datetime import datetime

from pydantic import BaseModel


class HostToastOut(BaseModel):
    """A queued native toast waiting for the host to pop it."""

    id: int
    source: str
    title: str
    content: str
    created_at: datetime
    delivered: bool = False

    model_config = {"from_attributes": True}