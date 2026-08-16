from pydantic import BaseModel, Field


class PorchStartOut(BaseModel):
    conversation_id: int = Field(description="The porch conversation for this device")
    opening: str = Field(description="Mira's first, unprompted words")
    ended: bool = Field(
        default=False,
        description="The porch has already run out of room for this device",
    )


class PorchStatusOut(BaseModel):
    conversation_id: int = Field(description="The porch conversation for this device")
    ended: bool = Field(description="Whether the porch has run out of room")
    verdict: str | None = Field(
        default=None,
        description="Mira's honest read — liked|mixed|not_liked. Her private "
        "moments are never exposed, only this verdict.",
    )
