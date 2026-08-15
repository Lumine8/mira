from pydantic import BaseModel, Field


class PorchStartOut(BaseModel):
    conversation_id: int = Field(description="The porch conversation for this device")
    opening: str = Field(description="Mira's first, unprompted words")
    ended: bool = Field(
        default=False,
        description="The porch has already run out of room for this device",
    )
