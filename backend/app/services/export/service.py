"""Export all conversations to a readable markdown archive.

The file is regenerated from scratch each time so it can never drift from the
database — append-only logs would silently drop edits or deletions. It is
written after every message commit, guarded by a lock so concurrent writers
(mind loop, tool renders, conversation turns) cannot interleave.

Regeneration is cheap at these volumes and happens in a background thread so a
conversation turn is never slowed by the write.
"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Message

logger = logging.getLogger("mira.export")

_lock = threading.Lock()


def _fmt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _speaker_label(m: Message) -> str:
    return "**You**" if m.speaker == "user" else "**Mira**"


def _render_message(m: Message) -> str:
    source = m.source if m.source and m.source != "text" else ""
    header = f"{_speaker_label(m)}"
    if source:
        header += f" *({source})*"
    body = m.content or ""
    if m.image:
        body = (body + "\n\n_[image attached — see the interface]_").strip()
    return f"{header} — {_fmt(m.created_at)}:\n\n{body}"


def render_conversations(db: Session) -> str:
    """Render every conversation, oldest first, into a single markdown doc."""
    conversations = db.execute(
        select(Conversation).order_by(Conversation.started_at.asc(), Conversation.id.asc())
    ).scalars()
    parts = [
        "# Mira — Full Conversation Log",
        "",
        f"_Generated: {_fmt(datetime.now(timezone.utc))}_",
        "",
        "Every conversation with Mira from the beginning, most recent at the bottom.",
        "",
    ]
    for conv in conversations:
        msgs = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.asc())
        ).scalars()
        parts.append("---")
        parts.append("")
        parts.append(
            f"## Conversation #{conv.id} — started {_fmt(conv.started_at)}"
        )
        parts.append("")
        parts.append(f"- **Type:** {conv.kind} · **Messages:** {len(list(msgs))}")
        if conv.summary:
            parts.append(f"- **Summary:** {conv.summary}")
        parts.append("")
        msgs = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.asc())
        ).scalars()
        for m in msgs:
            parts.append(_render_message(m))
            parts.append("")
    return "\n".join(parts)


def write_archive(path: str | Path) -> None:
    """Regenerate the archive from the DB. Safe to call on every message
    commit; the lock serializes writers and the whole file is rebuilt."""
    if not path:
        return
    from app.db.session import SessionLocal

    with _lock:
        try:
            db = SessionLocal()
            try:
                text = render_conversations(db)
            finally:
                db.close()
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - never break a turn
            logger.warning("conversation archive write failed: %s", exc)


def schedule_archive_write(path: str | Path) -> None:
    """Write the archive off the hot path so a turn is never blocked on disk."""
    import threading as _t

    _t.Thread(target=write_archive, args=(path,), daemon=True).start()
