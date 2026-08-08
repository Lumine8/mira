import asyncio
import base64
import logging
import re
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings
from app.services.ai.base import AIProvider

logger = logging.getLogger("mira.ollama")

_DATA_URL_RE = re.compile(r"^data:[^;]+;base64,(.+)$", re.DOTALL)

_MAX_RETRIES = 3
_BASE_DELAY = 2.0


def _prepare(messages: list[dict]) -> list[dict]:
    """Translate internal messages (with an optional ``image`` data URL) into
    Ollama's format: base64 image moved into the message's ``images`` array."""
    out: list[dict] = []
    for msg in messages:
        m = dict(msg)
        image = m.pop("image", None)
        if image:
            match = _DATA_URL_RE.match(image)
            payload = match.group(1) if match else image
            m["images"] = [base64.b64encode(base64.b64decode(payload)).decode()]
        out.append(m)
    return out


class OllamaProvider(AIProvider):
    """Talks to a local Ollama server (streaming chat + embeddings)."""

    name = "ollama"

    def __init__(self, host: str | None = None, model: str | None = None, embed_model: str | None = None):
        settings = get_settings()
        self.host = (host or settings.ollama_host).rstrip("/")
        self.model = model or settings.ollama_llm_model
        self.embed_model = embed_model or settings.ollama_embed_model
        self.num_gpu = settings.ollama_num_gpu
        self.max_tokens = settings.ollama_max_tokens

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        timeout: int = 180,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await client.request(method, url, json=json, timeout=timeout)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 503 and attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "ollama queue full (503), retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": _prepare(messages),
            "stream": True,
            # gemma4 spends its first ~60-80s silently in a `thinking` phase on
            # CPU, which reads as "stuck" and eats the token budget. Turn it off
            # (top-level, not in options) so the visible reply starts immediately.
            "think": False,
            # Keep the model resident for a while after use, so returning to a
            # conversation doesn't pay a multi-GB reload.
            "keep_alive": "30m",
            "options": {
                "num_predict": max_tokens or self.max_tokens,
                "temperature": temperature,
                "num_gpu": self.num_gpu,
            },
        }
        # client.stream() returns an async context manager, not a response, so it
        # can't go through _request_with_retry. Retry here instead: a 503 happens
        # at request time (before any token streams), so re-issuing is safe.
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                # CPU-only inference is slow (~60-80s a reply) and the mind loop
                # shares the same Ollama, so leave room for the queue to drain.
                async with httpx.AsyncClient(timeout=300) as client, client.stream(
                    "POST", f"{self.host}/api/chat", json=payload
                ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            chunk = _parse_chat_line(line)
                            if chunk:
                                yield chunk
                return
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 503 and attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "ollama queue full (503), retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "ollama unavailable (%s), retrying in %.1fs (attempt %d/%d)",
                        type(exc).__name__,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    async def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": _prepare(messages),
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
                "num_gpu": self.num_gpu,
            },
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await self._request_with_retry(
                client, "POST", f"{self.host}/api/chat", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        return (data.get("message") or {}).get("content", "")

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{self.host}/api/embed", json={"model": self.embed_model, "input": text})
            resp.raise_for_status()
            data = resp.json()
        embeddings = data.get("embeddings") or data.get("data", [])
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            return embeddings[0]
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], dict):
            return embeddings[0].get("embedding", [])
        raise ValueError(f"unexpected embed response from ollama: {data}")


def _parse_chat_line(line: str) -> str | None:
    import json

    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    msg = obj.get("message") or {}
    content = msg.get("content")
    if not content:
        return None
    # gemma4 sometimes emits a stray blockquote wrapper token.
    stripped = content.strip().lower()
    if stripped in ("<blockquote>", "</blockquote>"):
        return None
    return content
