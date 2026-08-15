"""A tiny in-process hub for pushing live events to the web app.

The mind loop uses it to announce self-initiated messages (Mira speaking to the
user on her own) the instant they are written, so the frontend can show a banner
and fire a browser notification without polling.

Clients connect as a user, and events are routed by user_id: a replica's inner
life never reaches the founder's browser.
"""

import asyncio
import json
import logging
import threading

from fastapi import WebSocket

logger = logging.getLogger("mira.broadcast")


class LiveHub:
    def __init__(self) -> None:
        self._clients: dict[int, set[WebSocket]] = {}
        self._lock = threading.Lock()

    async def connect(self, ws: WebSocket, user_id: int) -> None:
        await ws.accept()
        with self._lock:
            self._clients.setdefault(user_id, set()).add(ws)

    def disconnect(self, ws: WebSocket, user_id: int) -> None:
        with self._lock:
            clients = self._clients.get(user_id)
            if clients is None:
                return
            clients.discard(ws)
            if not clients:
                self._clients.pop(user_id, None)

    async def broadcast(self, obj: dict, user_id: int) -> None:
        payload = json.dumps(obj, default=str)
        with self._lock:
            clients = list(self._clients.get(user_id, set()))
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                with self._lock:
                    self._clients.get(user_id, set()).discard(ws)


live_hub = LiveHub()


def broadcast_later(obj: dict, user_id: int) -> None:
    """Broadcast from synchronous code (routes, services) without blocking.

    If a running loop exists, schedule the broadcast on it; otherwise run the
    hub on a short-lived loop in a daemon thread. Safe to call from anywhere.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        loop.create_task(live_hub.broadcast(obj, user_id))
        return

    def _run() -> None:
        asyncio.run(live_hub.broadcast(obj, user_id))

    threading.Thread(target=_run, daemon=True).start()
