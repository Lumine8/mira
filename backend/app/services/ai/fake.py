from collections.abc import AsyncIterator

from app.services.ai.base import AIProvider


class FakeProvider(AIProvider):
    """Deterministic in-memory provider for tests and offline dev."""

    name = "fake"

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or ["This is a fake reply.", "Streaming works."])
        self._calls: list[list[dict[str, str]]] = []

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        self._calls.append(messages)
        reply = self.responses[min(len(self._calls) - 1, len(self.responses) - 1)]
        for token in reply.split(" "):
            yield token + " "

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        self._calls.append(messages)
        reply = self.responses[min(len(self._calls) - 1, len(self.responses) - 1)]
        return reply

    async def embed(self, text: str) -> list[float]:
        return [float(len(text)) % 10] * 768
