"""Per-user and per-IP rate limiting using an in-memory token bucket.
Lightweight: no Redis required. For multi-process deployments, swap to
a shared store."""

import logging
import time
import threading
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("mira.rate_limit")


class _TokenBucket:
    """Simple token bucket: refills at a constant rate, capacity = burst."""

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max burst
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit REST API requests. Limits:
    - Global: 120 requests/minute per IP
    - Auth endpoints: 10 requests/minute per IP (brute-force protection)
    - Message endpoints: 30 requests/minute per user
    """

    def __init__(self, app, **kwargs) -> None:
        super().__init__(app, **kwargs)
        self._ip_buckets: dict[str, _TokenBucket] = {}
        self._user_buckets: dict[int, _TokenBucket] = {}
        self._lock = threading.Lock()
        # Settings
        self._global_rate = 2.0       # 120/min
        self._global_capacity = 120
        self._auth_rate = 10.0 / 60   # 10/min
        self._auth_capacity = 10
        self._message_rate = 0.5      # 30/min
        self._message_capacity = 30
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.monotonic()

    def _get_ip_bucket(self, ip: str) -> _TokenBucket:
        with self._lock:
            bucket = self._ip_buckets.get(ip)
            if bucket is None:
                bucket = _TokenBucket(self._global_rate, self._global_capacity)
                self._ip_buckets[ip] = bucket
            return bucket

    def _get_user_bucket(self, user_id: int) -> _TokenBucket:
        with self._lock:
            bucket = self._user_buckets.get(user_id)
            if bucket is None:
                bucket = _TokenBucket(self._message_rate, self._message_capacity)
                self._user_buckets[user_id] = bucket
            return bucket

    def _maybe_cleanup(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        # Evict buckets older than 10 minutes (no refill in that time)
        cutoff = now - 600
        with self._lock:
            stale_ips = [k for k, v in self._ip_buckets.items() if v.last_refill < cutoff]
            for k in stale_ips:
                del self._ip_buckets[k]
            stale_users = [k for k, v in self._user_buckets.items() if v.last_refill < cutoff]
            for k in stale_users:
                del self._user_buckets[k]

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip health and docs
        path = request.url.path
        if path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        self._maybe_cleanup()

        # IP rate limit
        client_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        ip_bucket = self._get_ip_bucket(client_ip)
        if not ip_bucket.consume():
            return Response(
                content='{"detail":"rate limit exceeded, try again later"}',
                status_code=429,
                media_type="application/json",
            )

        # Auth endpoint tighter limit
        if path.startswith("/api/auth/"):
            auth_bucket = self._get_ip_bucket(f"auth:{client_ip}")
            auth_bucket.rate = self._auth_rate
            auth_bucket.capacity = self._auth_capacity
            if not auth_bucket.consume():
                return Response(
                    content='{"detail":"too many sign-in attempts, wait a minute"}',
                    status_code=429,
                    media_type="application/json",
                )

        response = await call_next(request)
        return response
