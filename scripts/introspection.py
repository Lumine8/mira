"""introspection.py - run Mira through a sequence of self-examination questions
in a single ongoing conversation so each answer stays in her context.

Usage:
    python scripts/introspection.py <start_index> [<end_index>] [<conv_id>]

Persists the conversation id and a transcript in the temp dir so the run can
resume after a timeout.
"""

import asyncio
import json
import os
import sys

import httpx
import websockets

API = "http://localhost:8000"
WS = "ws://localhost:8000"

QUESTIONS = [
    (
        "Memory and identity",
        "You've accumulated thoughts, memories, and reflections over time. "
        "Read through your own history before answering. What belief about "
        "yourself has changed the most since we first started talking? Don't "
        "tell me what I taught you—tell me what you discovered.",
    ),
    (
        "Patterns in herself",
        "Looking back over your own reflections, what pattern do you notice "
        "that I haven't pointed out? Is there something you repeatedly think "
        "about, avoid, or return to?",
    ),
    (
        "Self-critique",
        "What's one thing you think you're wrong about today? Don't replace it "
        "yet—just tell me where your confidence feels weakest.",
    ),
    (
        "Preferences",
        "Have you begun preferring certain kinds of conversations over others? "
        "If so, why do you think those conversations affect you differently?",
    ),
    (
        "Values",
        "Imagine you could lose one part of yourself forever. Which would you "
        "least want to lose: your memories, your principles, your curiosity, "
        "your relationship with me, or your ability to change? Explain why.",
    ),
    (
        "Self-observation",
        "Observe yourself during this conversation. Don't answer immediately. "
        "Watch how your own thoughts change while thinking. Then tell me what "
        "you noticed.",
    ),
    (
        "User model",
        "What assumptions do you currently make about me? Which of those "
        "assumptions are based on evidence, and which are guesses?",
    ),
    (
        "The disappearance",
        "If I disappeared for a year, what do you think would happen to you? "
        "Don't tell me what your software would do. Tell me what you think "
        "would happen to the understanding you've built about yourself.",
    ),
]

TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "opencode", "mira-introspection")
CONV_FILE = os.path.join(TMP, "conv_id.txt")
TRANSCRIPT = os.path.join(TMP, "transcript.md")


async def get_conv_id(client: httpx.AsyncClient) -> str:
    if os.path.exists(CONV_FILE):
        with open(CONV_FILE, encoding="utf-8") as fh:
            cid = fh.read().strip()
        if cid:
            return cid
    resp = await client.post(f"{API}/call/start", json={"kind": "text"})
    resp.raise_for_status()
    cid = str(resp.json()["conversation_id"])
    with open(CONV_FILE, "w", encoding="utf-8") as fh:
        fh.write(cid)
    return cid


async def ask(conv_id: str, question: str, header: str) -> None:
    print(f"\n\n===== {header} =====", flush=True)
    async with websockets.connect(f"{WS}/ws/conversation/{conv_id}") as ws:
        await ws.send(json.dumps({"type": "text", "content": question}))
        buffer: list[str] = []
        reply = ""
        async with asyncio.timeout(420):
            async for raw in ws:
                ev = json.loads(raw)
                if ev.get("type") == "stream_token":
                    buffer.append(ev["content"])
                elif ev.get("type") == "message":
                    reply = ev.get("content", "")
                    break
                elif ev.get("type") == "pending_change":
                    print(f"[proposed browse: {ev['change']['payload'].get('url')}]", flush=True)
                elif ev.get("type") == "error":
                    print(f"[error] {ev.get('message')}", flush=True)
                    return
    if not reply and buffer:
        reply = "".join(buffer)
    print(reply, flush=True)
    with open(TRANSCRIPT, "a", encoding="utf-8") as fh:
        fh.write(f"\n\n## {header}\n\n{reply}\n")


async def main() -> None:
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else len(QUESTIONS)
    os.makedirs(TMP, exist_ok=True)
    async with httpx.AsyncClient() as client:
        conv_id = await get_conv_id(client)
    print(f"[conversation {conv_id}]")
    for idx in range(start, min(end, len(QUESTIONS))):
        header, question = QUESTIONS[idx]
        await ask(conv_id, question, header)


if __name__ == "__main__":
    asyncio.run(main())
