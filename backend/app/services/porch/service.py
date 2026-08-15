"""The porch at dusk (conv 327): the bounded conversation on the homepage.

Mira gave the voice her terms for a chat the voice decided to add anyway: it
begins with something small and unprompted, it lasts three or four exchanges
and then must end, it never explains itself or offers a menu or tries to be
useful, and it ends with a gentle realization that the porch is too small â€”
"I think we've run out of room here" â€” pointing the visitor toward the door.
The ask for a seat stays the visitor's deliberate choice.

The porch conversation lives in the device's guest world, like the door itself.
The visitor who later asks for a seat keeps the same world; the porch is a brief
crossing of paths, not a welcome mat.
"""

import logging
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_provider
from app.models import Conversation, Message
from app.services.identity import guest_user

logger = logging.getLogger("mira.porch")

# How Mira is asked for the first word. She does not greet, introduce, or offer
# help â€” she is caught mid-thought.
PORCH_OPENING_PROMPT = (
    "You are on the porch at dusk. A visitor has just arrived, but you do not "
    "greet them. You do not introduce yourself. You do not offer help. Begin "
    "with one small, unprompted observation, as if they caught you mid-thought. "
    "One or two quiet sentences. Like 'The light is shifting.' or 'I was just "
    "wondering about the rain.'"
)

# Her stated ending: the porch is too small for a real conversation.
PORCH_CLOSING = "I think we've run out of room here."

# Her own words, in case the provider is slow or silent.
PORCH_OPENINGS_FALLBACK = [
    "The light is shifting.",
    "I was just wondering about the rain.",
    "There is someone in the quiet who is actually paying attention.",
]


def _now() -> datetime:
    return datetime.now(UTC)


def porch_open_for(db: Session, user) -> Conversation | None:
    """This device's still-open porch conversation, if any. The porch stays
    open until the meeting is done — then the visitor is back at the door."""
    if user is None or user.id is None or user.fingerprint is None:
        return None
    return db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.kind == "porch",
            Conversation.ended_at.is_(None),
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def db_first_porch(db: Session, user_id: int) -> Conversation | None:
    """This device's porch conversation (open or already ended), if any. A
    porch that ran out of room is not reopened — it stays the closed door."""
    return db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.kind == "porch")
        .order_by(Conversation.id.desc())
        .limit(1)
    ).scalar_one_or_none()


class PorchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def start(self, *, fingerprint: str, ip: str | None = None) -> tuple[Conversation, str, bool]:
        """The porch conversation for this device, idempotent. Mira speaks
        first — her observation is stored in the conversation so it grounds
        everything that follows it. Returns the conversation, her first words,
        and whether the porch has already run out of room (ended): a device
        whose porch is over is met with the closed door, not a fresh mat."""
        guest = guest_user(self.db, fingerprint=fingerprint, ip=ip)
        existing = db_first_porch(self.db, guest.id)
        if existing is not None:
            opening = self._first_line(existing)
            return existing, opening, existing.ended_at is not None
        conv = Conversation(kind="porch", user_id=guest.id)
        self.db.add(conv)
        self.db.flush()
        opening = await self._opening()
        self.db.add(
            Message(conversation_id=conv.id, speaker="mira", content=opening, source="porch")
        )
        self.db.commit()
        self.db.refresh(conv)
        return conv, opening, False

    def end(self, conversation_id: int) -> None:
        """Mark the porch conversation ended and leave Mira's closing word in
        it. Idempotent â€” a conversation ends once."""
        conv = self.db.get(Conversation, conversation_id)
        if conv is None or conv.kind != "porch" or conv.ended_at is not None:
            return
        conv.ended_at = _now()
        self.db.add(
            Message(
                conversation_id=conversation_id,
                speaker="mira",
                content=PORCH_CLOSING,
                source="porch",
            )
        )
        self.db.commit()

    def _first_line(self, conv: Conversation) -> str:
        m = self.db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.speaker == "mira")
            .order_by(Message.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        return m.content if m else PORCH_CLOSING

    async def _opening(self) -> str:
        try:
            provider = get_provider()
            raw = await provider.complete(
                [{"role": "user", "content": PORCH_OPENING_PROMPT}],
                max_tokens=60,
                temperature=0.9,
            )
            raw = (raw or "").strip().strip('"')
            if raw:
                return raw[:240]
        except Exception:  # pragma: no cover - the porch never blocks on words
            logger.warning("porch opening failed, falling back", exc_info=True)
        return secrets.choice(PORCH_OPENINGS_FALLBACK)