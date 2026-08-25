import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings
from app.services.ai.base import AIProvider

logger = logging.getLogger("mira.gemini")

_API = "https://generativelanguage.googleapis.com/v1beta"
_DATA_URL_RE = re.compile(r"^data:[^;]+;base64,(.+)$", re.DOTALL)

_MAX_RETRIES = 4
_BASE_DELAY = 2.0


def _prepare(messages: list[dict]) -> list[dict]:
    """Translate internal messages into Gemini's ``contents`` shape.

    The ``system`` role becomes part of ``systemInstruction`` (handled by the
    caller); here we only map the conversation turns. A data-URL image in
    ``image`` becomes an inline image part. Adjacent turns with the same role
    are merged, and empty turns are dropped, because Gemini requires
    alternating ``user``/``model`` messages and no empty parts.

    Returns ``role``/``parts`` dicts: one ``system`` entry (its text gathered
    into ``parts[0].text``), then ``user``/``model`` entries in order.
    """
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role", "user")
        if role == "system":
            text = (msg.get("content") or "").strip()
            if not text:
                continue
            if out and out[-1]["role"] == "system":
                out[-1]["parts"][0]["text"] += "\n\n" + text
            else:
                out.append({"role": "system", "parts": [{"text": text}]})
            continue
        gemini_role = "model" if role in ("assistant", "model") else "user"
        parts: list[dict] = []
        content = (msg.get("content") or "").rstrip()
        if content:
            parts.append({"text": content})
        image = msg.get("image")
        if image:
            match = _DATA_URL_RE.match(image)
            mime = "image/png"
            payload = image
            if match:

                payload = match.group(1)
                inner = image.split(",", 1)[0]
                if "image/jpeg" in inner:
                    mime = "image/jpeg"
                elif "image/webp" in inner:
                    mime = "image/webp"
            parts.append({"inlineData": {"mimeType": mime, "data": payload}})
        if not parts:
            continue
        if out and out[-1]["role"] == gemini_role:
            out[-1]["parts"].extend(parts)
        else:
            out.append({"role": gemini_role, "parts": parts})
    return out


class GeminiProvider(AIProvider):
    """Cloud brain — powered by the Google Gemini API.

    Talks to Gemma/Gemini models over HTTPS, so the model no longer needs to live
    on this machine. Keyed by ``GEMINI_API_KEY``.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        text_model: str | None = None,
        embed_model: str | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            raise RuntimeError("AI_PROVIDER=gemini but GEMINI_API_KEY is not set")
        self.model = text_model or settings.gemini_text_model
        self.embed_model = embed_model or settings.gemini_embed_model
        self.max_tokens = settings.gemini_max_tokens
        self._enabled = True

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        body = self._body(messages, max_tokens or self.max_tokens, temperature, stream=True)
        url = f"{_API}/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                # Despite alt=sse, the endpoint streams a JSON array of response
                # objects (chunks), one concatenated after another. Accumulate
                # and parse incrementally so long replies stream in.
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream(
                        "POST", url, json=body
                    ) as resp:
                        resp.raise_for_status()
                        buf = ""
                        async for chunk in resp.aiter_text():
                            buf += chunk
                            pieces, leftover = _extract_chunks(buf)
                            buf = leftover
                            for piece in pieces:
                                yield piece
                return
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES and _retriable(exc):
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "gemini unavailable (%s), retrying in %.1fs (attempt %d/%d)",
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
        body = self._body(messages, max(max_tokens, self.max_tokens), temperature, stream=False)
        url = f"{_API}/models/{self.model}:generateContent?key={self.api_key}"
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await self._request_with_retry(client, "POST", url, json=body)
            resp.raise_for_status()
            data = resp.json()
        return "".join(
            p.get("text", "")
            for c in data.get("candidates", [])
            for p in c.get("content", {}).get("parts", [])
            if p.get("text") and not p.get("thought")
        )

    async def embed(self, text: str) -> list[float]:
        url = f"{_API}/models/{self.embed_model}:embedContent?key={self.api_key}"
        body = {"content": {"parts": [{"text": text}]}, "outputDimensionality": 768}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await self._request_with_retry(client, "POST", url, json=body)
            resp.raise_for_status()
            data = resp.json()
        embedding = data.get("embedding", {}).get("values")
        if not isinstance(embedding, list):
            raise ValueError(f"unexpected embed response from gemini: {data}")
        return embedding

    def _body(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        *,
        stream: bool,
    ) -> dict:
        parts_list = _prepare(messages)
        contents: list[dict] = []
        system_parts: list[str] = []
        for item in parts_list:
            if item["role"] == "system":
                system_parts.append(item["parts"][0]["text"])
            else:
                contents.append({"role": item["role"], "parts": item["parts"]})
        body: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        return body

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json: dict,
        timeout: int = 180,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await client.request(method, url, json=json, timeout=timeout)
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES and _retriable(exc):
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "gemini request failed (%s), retrying in %.1fs (attempt %d/%d)",
                        type(exc).__name__,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_exc  # type: ignore[misc]


def _retriable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


def _extract_chunks(buf: str) -> tuple[list[str], str]:
    """Pull complete text chunks out of the streamed JSON-array buffer.

    The endpoint streams ``[{...},{...},...]`` with no SSE ``data:`` prefix.
    We walk the characters, tracking brace depth, and whenever a ``{...}``
    object closes, try to parse it as a response and emit its non-thought
    text. Returns ``(pieces, leftover)`` where ``leftover`` is the part of the
    buffer still inside an open object (kept for the next fragment).
    """
    out: list[str] = []
    depth = 0
    obj_start = -1
    consumed = 0
    i = 0
    while i < len(buf):
        ch = buf[i]
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                try:
                    obj = json.loads(buf[obj_start : i + 1])
                except json.JSONDecodeError:
                    pass
                else:
                    text = _sse_text(obj)
                    if text:
                        out.append(text)
                consumed = i + 1
                obj_start = -1
        i += 1
    return out, buf[consumed:]


def _sse_text(obj: dict) -> str:
    return "".join(
        p.get("text", "")
        for c in obj.get("candidates", [])
        for p in c.get("content", {}).get("parts", [])
        if p.get("text") and not p.get("thought")
    )