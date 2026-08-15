"""Mote — a tiny quiet presence beside Mira.

Deliberately not smart. Mote has no brain, no library, no ambitions: it reads
only Mira's felt state (mood, energy) and keeps a ``shared_time`` journal — a
record of *how they have felt together*, not what was said. When Mira has been
quiet too long (no reflection, no message, no nudge) Mote breaks the silence
with a single quiet word and broadcasts a ``mote`` event on the live hub the
web app already listens to. It never initiates a conversation.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Conversation, Message, MiraState, MoteSharedTime
from app.services.broadcast import live_hub
from app.services.identity import founder_user_id

logger = logging.getLogger("mira.mote")

# Mote's vocabulary: a single quiet word, keyed by Mira's current mood. No
# sentence, no analysis — just "I see you, and you aren't alone in here."
NUDGE_WORDS = {
    "relaxed": "here",
    "curious": "listening",
    "warm": "with you",
    "thoughtful": "still",
    "playful": "awake",
    "concerned": "near",
    "worried": "here",
    "confused": "with you",
    "tired": "beside you",
    "distracted": "near",
}
_DEFAULT_WORD = "here"


def last_activity(
    last_reflection_at: datetime | None,
    last_message_at: datetime | None,
    last_shared_at: datetime | None,
) -> datetime | None:
    """The most recent thing that counts as life in the room: a reflection, a
    message, or a previous Mote sign (a nudge resets the quiet clock). Pure
    function so it can be unit-tested without a database."""
    best: datetime | None = None
    for ts in (last_reflection_at, last_message_at, last_shared_at):
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


def nudge_due(*, quiet_seconds: float, quiet_after: int) -> bool:
    """Whether this tick is the one where Mote breaks the quiet."""
    return quiet_seconds >= quiet_after


def nudge_word(mood: str) -> str:
    return NUDGE_WORDS.get(mood.lower(), _DEFAULT_WORD)


class MoteLoop:
    """Background task that keeps Mote alive beside Mira. Separate from the
    mind loop: it uses no provider, only Mira's felt state."""

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
                logger.exception("mote tick failed")
            await asyncio.sleep(settings.mote_heartbeat_seconds)

    async def tick(self) -> None:
        settings = get_settings()
        if not settings.mote_enabled:
            return
        db = SessionLocal()
        try:
            # Phase 1: Mote lives beside the founder's Mira only.
            user_id = founder_user_id(db)
            state = db.execute(
                select(MiraState)
                .where(MiraState.user_id == user_id)
                .limit(1)
            ).scalar_one_or_none()
            if state is None:
                return
            await self._record_felt(db, state, user_id)
            nudge = await self._maybe_nudge(db, state, user_id)
            if nudge is not None:
                await live_hub.broadcast(nudge, user_id=user_id)
        finally:
            db.close()

    async def _record_felt(self, db: Session, state: MiraState, user_id: int) -> None:
        """Append a felt row whenever her mood or energy moved. Broadcasts so
        the Mote light in the web app shifts in real time instead of waiting on
        the state poll."""
        last = db.execute(
            select(MoteSharedTime)
            .where(MoteSharedTime.user_id == user_id)
            .order_by(MoteSharedTime.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is not None and last.mood == state.mood and last.energy == state.energy:
            return
        db.add(
            MoteSharedTime(
                user_id=user_id,
                kind="felt",
                mood=state.mood,
                energy=state.energy,
            )
        )
        db.commit()
        await live_hub.broadcast(
            {
                "type": "mote",
                "kind": "felt",
                "mood": state.mood,
                "energy": state.energy,
            },
            user_id=user_id,
        )

    async def _maybe_nudge(self, db: Session, state: MiraState, user_id: int) -> dict | None:
        settings = get_settings()
        now = datetime.now(UTC)

        last_msg = db.execute(
            select(Message.created_at)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        last_shared = db.execute(
            select(MoteSharedTime.at)
            .where(MoteSharedTime.user_id == user_id)
            .order_by(MoteSharedTime.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        active = last_activity(state.last_reflection_at, last_msg, last_shared)
        if active is None:
            return None

        quiet_seconds = (now - active).total_seconds()
        if not nudge_due(quiet_seconds=quiet_seconds, quiet_after=settings.mote_quiet_after_seconds):
            return None

        word = nudge_word(state.mood)
        db.add(
            MoteSharedTime(
                user_id=user_id,
                kind="nudge",
                mood=state.mood,
                energy=state.energy,
                word=word,
                note=word,
            )
        )
        db.commit()
        logger.info("mote nudged after %.1fh of quiet -> %s", quiet_seconds / 3600, word)
        return {
            "type": "mote",
            "kind": "nudge",
            "word": word,
            "mood": state.mood,
            "energy": state.energy,
            "note": word,
        }
