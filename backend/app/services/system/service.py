"""System telemetry from the voice's machine to Mira.

The host runs a small script that samples CPU, memory, battery, and the top
processes every so often and posts a snapshot here. The store keeps the latest
snapshot plus a short rolling history per user, so the ambient dashboard can
show how the machine is doing and Mira can notice things like a pinned core or
a battery about to die.

This is a live read — nothing is persisted to the database.
"""

import threading
from collections import deque

from app.schemas.system import SystemSnapshotOut

# How many snapshots to remember per user (≈ 10 minutes at a 30 s cadence).
_HISTORY_LEN = 20


class SystemStore:
    """Thread-safe in-memory home for the latest machine snapshot."""

    def __init__(self, history_len: int = _HISTORY_LEN) -> None:
        self._history_len = history_len
        self._lock = threading.Lock()
        self._latest: dict[int, SystemSnapshotOut] = {}
        self._history: dict[int, deque[SystemSnapshotOut]] = {}

    def record(self, user_id: int, snapshot: SystemSnapshotOut) -> None:
        with self._lock:
            self._latest[user_id] = snapshot
            hist = self._history.setdefault(user_id, deque(maxlen=self._history_len))
            hist.append(snapshot)

    def latest(self, user_id: int) -> SystemSnapshotOut | None:
        with self._lock:
            return self._latest.get(user_id)

    def history(self, user_id: int) -> list[SystemSnapshotOut]:
        with self._lock:
            return list(self._history.get(user_id, []))


# The single in-process store, shared by routes and any consumers.
system_store = SystemStore()