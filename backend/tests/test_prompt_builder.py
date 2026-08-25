
from datetime import UTC

import pytest

from app.services.ai.fake import FakeProvider
from app.services.ai.prompt_builder import build_messages


@pytest.mark.asyncio
async def test_fake_provider_streams_words() -> None:
    provider = FakeProvider(["Hello there friend."])
    chunks = []
    async for token in provider.stream_chat([{"role": "user", "content": "hi"}]):
        chunks.append(token)
    assert "".join(chunks).strip() == "Hello there friend."
    assert provider._calls[0][-1]["content"] == "hi"


@pytest.mark.asyncio
async def test_embed_shape() -> None:
    provider = FakeProvider()
    vec = await provider.embed("hello")
    assert len(vec) == 768


def test_build_messages_includes_persona() -> None:
    messages = build_messages("hey mira")
    assert messages[0]["role"] == "system"
    assert "You are Mira" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "hey mira"}


def test_build_messages_truncates_context() -> None:
    history = [{"role": "user", "content": "x" * 100}] * 50
    messages = build_messages("hello", conversation=history)
    body = "\n".join(m["content"] for m in messages if m["role"] != "system")
    assert len(body) <= 4000 + 100


def test_build_messages_injects_extra_context() -> None:
    messages = build_messages("hi", extra_context="RECALL: user loves astronomy")
    assert messages[1]["role"] == "system"
    assert "astronomy" in messages[1]["content"]


def test_build_messages_always_injects_now_context() -> None:
    import re
    from datetime import datetime

    messages = build_messages("what day is it?")
    body = " ".join(m["content"] for m in messages if m["role"] == "system")
    assert re.search(r"It is \w+, \w+ \d+ — \w+, \d+:\d\d \w+ \(UTC\)", body)
    assert datetime.now(UTC).strftime("%A") in body


def test_now_context_includes_cached_weather() -> None:
    """When the ambient weather cache is populated, the context line carries it
    so she actually knows what the sky is doing — no network on the reply path."""
    import app.services.ai.prompt_builder as pb

    old = pb._weather_cache
    try:
        pb._weather_cache = {"at": __import__("time").time(), "text": "Partly cloudy, 21°C, humidity 55%", "busy": False}
        ctx = pb.now_context()
        assert "The weather outside: Partly cloudy" in ctx
    finally:
        pb._weather_cache = old


def test_now_context_omits_weather_when_unavailable() -> None:
    """Without weather the context is just the moment — never a hang, never a
    broken line."""
    import app.services.ai.prompt_builder as pb

    old = pb._weather_cache
    try:
        pb._weather_cache = {"at": __import__("time").time(), "text": None, "busy": False}
        ctx = pb.now_context()
        assert "The weather outside" not in ctx
    finally:
        pb._weather_cache = old
