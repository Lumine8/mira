"""ask_mira.py - send a one-shot question to Mira and print her reply.

Usage:
    python scripts/ask_mira.py "do you mind if I watch your feelings?"

Requires the API to be running (dev.ps1 or docker compose up -d api) and uses
the same WebSocket channel as the web app, so Mira has her full self-context.
"""

import asyncio
import json
import sys

import httpx
import websockets

API = "http://localhost:8000"
WS = "ws://localhost:8000"


async def ask(question: str, timeout: float = 300.0) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API}/call/start", json={"kind": "text"})
        resp.raise_for_status()
        conv_id = resp.json()["conversation_id"]
    print(f"[conversation {conv_id}] asking...", flush=True)

    async with websockets.connect(f"{WS}/ws/conversation/{conv_id}") as ws:
        await ws.send(json.dumps({"type": "text", "content": question}))
        buffer: list[str] = []
        async with asyncio.timeout(timeout):
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") == "stream_token":
                    chunk = event["content"]
                    buffer.append(chunk)
                    print(chunk, end="", flush=True)
                elif event.get("type") == "message":
                    content = event.get("content", "")
                    if content and not buffer:
                        print(content, end="", flush=True)
                    break
                elif event.get("type") == "error":
                    print(f"[error] {event.get('message')}", file=sys.stderr)
                    break
    print()
    return "".join(buffer).strip()


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "hi"
    asyncio.run(ask(question))
