from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class AIProvider(ABC):
    """Interface every brain provider (Ollama, Gemini, fake) implements."""

    name: str = "base"

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        """Stream the model's reply text chunk by chunk."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        """Return the model's full reply as one string (non-streaming).

        Used for structured/short outputs like the self-reflection digest.
        """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a vector embedding for ``text``."""
