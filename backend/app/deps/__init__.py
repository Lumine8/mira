import hmac
from functools import lru_cache

from fastapi import Header, HTTPException, Query, WebSocket, status

from app.core.config import get_settings
from app.services.ai import AIProvider, create_provider


@lru_cache
def get_provider() -> AIProvider:
    """Single shared provider instance for the process."""
    return create_provider()


def _verify(token: str | None) -> None:
    """Compare a presented token against the configured one, constant-time.

    When no token is configured (local dev) auth is disabled and any request
    passes. When configured, a missing or wrong token is refused.
    """
    configured = get_settings().mira_access_token
    if not configured:
        return
    if not token:
        raise _unauthorized()
    if not hmac.compare_digest(token, configured):
        raise _unauthorized()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized: missing or invalid Mira access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_access_token(
    x_mira_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """Dependency for REST routes requiring Mira's access token."""
    _verify(x_mira_token or token)


def ws_authorized(token: str | None = Query(default=None)) -> bool:
    """Verify a WebSocket's `?token=` query param. Returns True if authorized,
    False (caller should close) when a token is configured but missing/wrong."""
    configured = get_settings().mira_access_token
    if not configured:
        return True
    return bool(token) and hmac.compare_digest(token, configured)