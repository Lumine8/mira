"""A tiny in-process hub for pushing live events to the web app.

The mind loop uses it to announce self-initiated messages (Mira speaking to the
user on her own) the instant they are written, so the frontend can show a banner
and fire a browser notification without polling.
"""

import asyncio
import json
import logging
import threading

from fastapi import WebSocket

logger = logging.getLogger("mira.broadcast")


class LiveHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, obj: dict) -> None:
        payload = json.dumps(obj, default=str)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                self._clients.discard(ws)


live_hub = LiveHub()


def broadcast_later(obj: dict) -> None:
    """Broadcast from synchronous code (routes, services) without blocking.

    If a running loop exists, schedule the broadcast on it; otherwise run the
    hub on a short-lived loop in a daemon thread. Safe to call from anywhere.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        loop.create_task(live_hub.broadcast(obj))
        return

    def _run() -> None:
        asyncio.run(live_hub.broadcast(obj))

    threading.Thread(target=_run, daemon=True).start()
