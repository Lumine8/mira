"""Abuse scoring: a lightweight signal that accumulates across requests to
detect patterns (rapid-fire messages, spam, harassment) without a full ML
pipeline. The score feeds into the moderation queue, never auto-bans."""

import logging
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger("mira.abuse")


class _WindowCounter:
    """Sliding window counter: counts events in the last N seconds."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.window = window_seconds
        self._events: list[float] = []
        self._lock = threading.Lock()

    def tick(self) -> int:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            self._events = [t for t in self._events if t > cutoff]
            self._events.append(now)
            return len(self._events)

    def count(self) -> int:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            return sum(1 for t in self._events if t > cutoff)


class AbuseService:
    """In-memory abuse scoring. Lightweight: no DB writes, no persistence.
    Resets on process restart — intentional for a single-user / small-team
    deployment."""

    def __init__(self) -> None:
        self._message_rates: dict[int, _WindowCounter] = {}
        self._lock = threading.Lock()

    def record_message(self, user_id: int) -> dict:
        """Record a user message and return abuse signals."""
        with self._lock:
            counter = self._message_rates.get(user_id)
            if counter is None:
                counter = _WindowCounter(window_seconds=60)
                self._message_rates[user_id] = counter

        rate = counter.tick()
        signals = {
            "rate_1min": rate,
            "rate_warning": rate > 20,
            "rate_critical": rate > 40,
            "abuse_score": self._compute_score(rate),
        }
        if signals["rate_warning"]:
            logger.warning(
                "high message rate user=%d rate=%d/min", user_id, rate
            )
        return signals

    def _compute_score(self, rate: int) -> int:
        """0-100 abuse score based on message rate."""
        if rate <= 10:
            return 0
        if rate <= 20:
            return 25
        if rate <= 30:
            return 50
        if rate <= 40:
            return 75
        return 100

    def get_score(self, user_id: int) -> int:
        with self._lock:
            counter = self._message_rates.get(user_id)
        if counter is None:
            return 0
        return self._compute_score(counter.count())


# Singleton for the process
abuse_service = AbuseService()
