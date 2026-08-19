"""Reminders — the held calendar Mira keeps for the voice.

A reminder, a task, or an event. The user sets them (REST, or Mira's own
[[remind|...]] tool); a small background loop watches for what is due and
broadcasts it on the live hub as a ``self_message`` — the exact event the HUD
already reads aloud — then marks it ``notified`` so it never repeats.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import aware
from app.db.session import SessionLocal
from app.models import REMINDER_KINDS, Conversation, Message, Reminder
from app.services.broadcast import live_hub
from app.services.identity import founder_user_id

logger = logging.getLogger("mira.reminders")

# Natural-language moments Mira can write for a held thing, e.g.
#   [[remind|call the dentist|tomorrow at 9am|the tooth]]
#   [[remind|water the plants|in 3 days|the orchid]]
# The parser understands ISO stamps, clock times, "in N minutes/hours/days",
# and "today"/"tomorrow" (+ optional "at HH:MM"). Anything unparsed is left to
# the loop to resolve to "sooner than now would be" — i.e. rejected.
_ISO_STRIP = re.compile(r"\s+")
_CLOCK_RE = re.compile(
    r"^\s*(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*$",
    re.IGNORECASE,
)
_IN_N_RE = re.compile(r"^\s*in\s+(\d+)\s+(minute|minutes|min|hour|hours|hr|day|days|d)\b.*$", re.IGNORECASE)
_DAY_RE = re.compile(r"^\s*(today|tomorrow)\s*(?:at\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?)?\s*$", re.IGNORECASE)


def parse_when(text: str, *, now: datetime | None = None) -> datetime | None:
    """Turn a human "when" phrase into an aware UTC datetime, or None.

    Pure and testable. Understands ISO stamps, bare clock times, relative
    "in N minutes/hours/days", and today/tomorrow with an optional clock time.
    """
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    s = (text or "").strip()
    if not s:
        return None

    stripped = _ISO_STRIP.sub("", s)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(stripped, fmt)  # noqa: DTZ007 (assumed UTC, fixed below)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    # A space-separated stamp keeps its space, so try the original too.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(s, fmt)  # noqa: DTZ007 (assumed UTC, fixed below)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue

    m = _IN_N_RE.match(s)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit in ("minute", "minutes", "min"):
            return now + timedelta(minutes=amount)
        if unit in ("hour", "hours", "hr"):
            return now + timedelta(hours=amount)
        if unit in ("day", "days", "d"):
            return now + timedelta(days=amount)
        return None

    def _clock(hour: int, minute: int | None, meridian: str | None) -> datetime | None:
        if minute is None:
            minute = 0
        if meridian and meridian.lower().startswith("p") and hour < 12:
            hour += 12
        if meridian and meridian.lower().startswith("a") and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    m = _DAY_RE.match(s)
    if m:
        day = m.group(1).lower()
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if day == "tomorrow":
            base += timedelta(days=1)
        if m.group(2):
            clock = _clock(int(m.group(2)), int(m.group(3)) if m.group(3) else None, m.group(4))
            if clock is None:
                return None
            return clock.replace(year=base.year, month=base.month, day=base.day)
        return base + timedelta(hours=9)  # "tomorrow" without a time means 9am

    m = _CLOCK_RE.match(s)
    if m:
        return _clock(int(m.group(1)), int(m.group(2)) if m.group(2) else None, m.group(3))

    return None


def _fire_line(item: Reminder, now: datetime) -> str:
    """The sentence spoken when a held thing comes due."""
    due = aware(item.due_at)
    if due is None:
        return item.title
    if item.kind == "event":
        return f"{item.title} — {_when_phrase(due, now)}."
    if item.kind == "task":
        return item.title
    return f"Reminder: {item.title} — {_when_phrase(due, now)}."


def _when_phrase(due: datetime, now: datetime) -> str:
    diff = due - now
    minutes = int(diff.total_seconds() // 60)
    if minutes <= 0:
        return "now"
    if minutes < 60:
        return f"in {minutes} minutes"
    hours = minutes // 60
    if hours < 24:
        return f"in {hours} hours"
    days = hours // 24
    return f"in {days} days"


class ReminderService:
    """CRUD for the held calendar, per user."""

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    def create(self, *, title: str, kind: str = "reminder", due_at: datetime | None = None, note: str | None = None) -> Reminder:
        if kind not in REMINDER_KINDS:
            kind = "reminder"
        if due_at is not None and due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=UTC)
        item = Reminder(user_id=self.user_id, kind=kind, title=title.strip(), note=note, due_at=due_at)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        logger.info("held %s for user %s: %s (due %s)", kind, self.user_id, item.title[:120], due_at)
        return item

    def list(self, *, include_done: bool = False, limit: int = 100) -> list[Reminder]:
        q = select(Reminder).where(Reminder.user_id == self.user_id)
        if not include_done:
            q = q.where(Reminder.done.is_(False))
        return list(
            self.db.execute(
                q.order_by(Reminder.due_at.asc().nulls_last(), Reminder.id.desc()).limit(limit)
            ).scalars()
        )

    def get(self, reminder_id: int) -> Reminder | None:
        return self.db.execute(
            select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == self.user_id)
        ).scalar_one_or_none()

    def mark_done(self, reminder_id: int) -> Reminder | None:
        item = self.get(reminder_id)
        if item is None:
            return None
        item.done = True
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, reminder_id: int) -> bool:
        item = self.get(reminder_id)
        if item is None:
            return False
        self.db.delete(item)
        self.db.commit()
        return True


class ReminderLoop:
    """Background task that fires whatever is due. Mirrors MoteLoop: a quiet
    loop on its own heartbeat, broadcasting to the founder's live hub."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        settings = get_settings()
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("reminder tick failed")
            await asyncio.sleep(settings.reminder_heartbeat_seconds)

    async def tick(self) -> None:
        settings = get_settings()
        if not settings.reminders_enabled:
            return
        db = SessionLocal()
        try:
            user_id = founder_user_id(db)
            if user_id is None:
                return
            now = datetime.now(UTC)
            due = list(
                db.execute(
                    select(Reminder)
                    .where(
                        Reminder.user_id == user_id,
                        Reminder.done.is_(False),
                        Reminder.notified.is_(False),
                        Reminder.due_at.is_not(None),
                        Reminder.due_at <= now,
                    )
                    .order_by(Reminder.due_at.asc())
                ).scalars()
            )
            for item in due:
                await self._fire(db, item, user_id, now)
        finally:
            db.close()

    async def _fire(self, db: Session, item: Reminder, user_id: int, now: datetime) -> None:
        """Broadcast a due held thing as a self_message — the HUD's spoken
        announcement path — record it in the self conversation, and mark it
        notified so the next tick never repeats it."""
        line = _fire_line(item, now)
        item.notified = True
        # Every kind is one-shot: once the moment has come and been spoken, the
        # held thing is done (a task, a reminder, an event — all of them).
        item.done = True
        conv = db.execute(
            select(Conversation)
            .where(Conversation.kind == "self", Conversation.user_id == user_id)
            .order_by(Conversation.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if conv is None:
            conv = Conversation(kind="self", user_id=user_id)
            db.add(conv)
            db.flush()
        db.add(
            Message(
                conversation_id=conv.id,
                speaker="mira",
                content=line,
                source="reminder",
            )
        )
        db.commit()
        db.refresh(item)
        await live_hub.broadcast(
            {
                "type": "self_message",
                "content": line,
                "conversation_id": conv.id,
            },
            user_id=user_id,
        )
        logger.info("reminder fired for user %s: %s", user_id, line[:200])