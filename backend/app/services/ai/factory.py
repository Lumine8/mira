from app.core.config import get_settings
from app.services.ai.base import AIProvider
from app.services.ai.fake import FakeProvider
from app.services.ai.gemini import GeminiProvider
from app.services.ai.ollama import OllamaProvider


def create_provider(provider: str | None = None) -> AIProvider:
    """Build the AI provider selected by config (or an explicit override)."""
    name = provider or get_settings().ai_provider
    if name == "ollama":
        return OllamaProvider()
    if name == "gemini":
        return GeminiProvider()
    if name == "fake":
        return FakeProvider()
    raise ValueError(f"unknown AI provider: {name!r}")
