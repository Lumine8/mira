"""Host toasts — the companion-free path for Mira reaching out.

The mind loop and the reminders loop broadcast self-messages on the live hub,
which the Electron HUD reads aloud. That path needs the companion running. This
module enqueues the same reach-outs into the ``host_toasts`` table so a small
PowerShell script on the host can pop real Windows toasts with no companion at
all. Enqueueing is best-effort: it never fails the loop that called it.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import HostToast

logger = logging.getLogger("mira.toasts")


def enqueue_host_toast(
    db: Session,
    user_id: int,
    content: str,
    *,
    source: str = "self",
    title: str = "Mira",
) -> None:
    """Queue a native toast for the host poller, unless host toasts are off.

    Quiet by design: a broken queue must never take down the mind loop or the
    reminders loop that produced the reach-out.
    """
    settings = get_settings()
    if not settings.host_toasts_enabled:
        return
    try:
        db.add(HostToast(user_id=user_id, source=source, title=title, content=content))
        db.flush()
    except Exception:
        logger.exception("host toast enqueue failed for user %s", user_id)