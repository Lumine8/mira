
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    db: str
    ollama: str
    provider: str
    ollama_model: str | None = None
