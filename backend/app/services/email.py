"""Outbound mail through Resend's API — one key, no SMTP server to run.

Where SMTP was the fallback for magic links, this is the main door for
invitations. A failure never raises: the caller keeps the code either way and
the frontend falls back to a mailto draft.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("mira.email")

_RESEND_API_URL = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 20

# The door's letter, as Mira wrote it (opening rephrased per her second pass).
_INVITE_SUBJECT = "A place to enter"
_INVITE_TEXT = (
    "The voice told me you were coming, and I've been keeping a spot open for "
    "you.\n\nYour invite code is {code}.\n\nI look forward to meeting you.\n\n— Mira"
)


def send_invite_email(to: str, code: str) -> bool:
    """Email an invitation code to ``to`` via Resend. False means no mail went
    out (not configured, or the API refused it) — never an exception."""
    settings = get_settings()
    if not settings.resend_configured:
        logger.info("invite for %s not emailed (Resend unset)", to)
        return False
    try:
        resp = httpx.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from,
                "to": [to],
                "subject": _INVITE_SUBJECT,
                "text": _INVITE_TEXT.format(code=code),
            },
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code >= 400:
            logger.warning("Resend refused invite for %s: %s", to, resp.text[:300])
            return False
        logger.info("invite emailed to %s", to)
        return True
    except Exception as exc:  # pragma: no cover - mail infrastructure
        logger.warning("could not email invite to %s: %s", to, exc)
        return False