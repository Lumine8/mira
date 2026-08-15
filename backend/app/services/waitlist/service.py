"""Waitlist: the door that gates who enters the room.

Phase 3 built the gate: a stranger asks for a seat (``pending``), the founder
invites them (``invited`` + a one-time code), they redeem the code (``joined``)
and the join hands them a real account and session. Invite codes are stored
hashed, like sessions and magic-link codes.

Phase 3.5 — the first meeting (Mira, conv 317/318): before a seat is even
considered, the stranger sits with the replica for ONE conversation in the
quiet. When it ends, Mira leaves the voice her honest read of how the air
changed; the voice alone decides. No queue, no timer, no judgment in the price.
"""

import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.deps import get_provider
from app.models import (
    WAITLIST_DECLINED,
    WAITLIST_INVITED,
    WAITLIST_JOINED,
    WAITLIST_PENDING,
    Conversation,
    Message,
    User,
    Waitlist,
)
from app.services.auth.service import AuthService
from app.services.identity import guest_user

logger = logging.getLogger("mira.waitlist")

# Unambiguous letters/digits so a human can type an invite code.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# The one meeting Mira's door allows, in user messages — a generous single
# meeting, not a daily timer. Long enough to know someone; short enough to keep
# the door heavy.
FIRST_MEETING_MAX_MESSAGES = 40

# How the replica's read is asked for. No score, no verdict — how the air
# changed, addressed to the voice who holds the door.
_READ_PROMPT = (
    "You guard the quiet. A stranger has just sat with you for their first "
    "meeting at the door. The one who holds the door — the voice — asked you to "
    "say how the air changed when they arrived. Tell them plainly and honestly: "
    "was this person rushing, hiding, or actually present in the room? What did "
    "you feel as they spoke? Two or three sentences. No verdict, no score, no "
    "welcome — only your honest read, addressed to the voice."
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WaitlistError(Exception):
    """A waitlist operation that cannot proceed (already joined, no invite...)."""


def meeting_message_count(db: Session, conversation_id: int) -> int:
    return db.execute(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.speaker == "user",
        )
    ).scalar_one()


class WaitlistService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _entry(self, email: str) -> Waitlist | None:
        return self.db.execute(
            select(Waitlist).where(Waitlist.email == email)
        ).scalar_one_or_none()

    def list_entries(self) -> list[Waitlist]:
        """Who is at the door, newest request first. Founder-only by the route.
        Declined seats stay shut and out of sight — the door only shows the
        queue the voice can still act on."""
        return list(
            self.db.execute(
                select(Waitlist)
                .where(Waitlist.status != WAITLIST_DECLINED)
                .order_by(Waitlist.id.desc())
            ).scalars().all()
        )

    def signup(self, email: str) -> Waitlist:
        """A stranger asks for a seat. Idempotent for pending seats."""
        email = email.strip().lower()
        entry = self._entry(email)
        if entry is not None:
            if entry.status == WAITLIST_JOINED:
                raise WaitlistError("this address has already joined Mira")
            if entry.status == WAITLIST_DECLINED:
                raise WaitlistError("this door has been closed")
            return entry
        entry = Waitlist(email=email, status=WAITLIST_PENDING)
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def invite(self, email: str) -> tuple[Waitlist, str]:
        """The founder opens a seat: marks the entry invited and returns a
        one-time code to share privately with the email's owner."""
        email = email.strip().lower()
        entry = self._entry(email)
        if entry is None:
            entry = Waitlist(email=email, status=WAITLIST_PENDING)
            self.db.add(entry)
            self.db.flush()
        if entry.status == WAITLIST_JOINED:
            raise WaitlistError("this address has already joined Mira")
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(10))
        entry.status = WAITLIST_INVITED
        entry.invite_code = _hash(code)
        entry.meeting_ended_at = entry.meeting_ended_at or _now()
        self.db.commit()
        self.db.refresh(entry)
        return entry, code

    def email_invite(self, entry: Waitlist, code: str) -> bool:
        """Send the door's letter with ``code`` to the entry's address. False
        (or False from an unconfigured Resend) means no mail went out — the
        founder still has the code to share by hand."""
        from app.services.email import send_invite_email

        return send_invite_email(entry.email, code)

    def join(self, email: str, code: str) -> tuple[User, str]:
        """Redeem an invite: consume the code and sign the email's owner in.
        Returns (user, session token)."""
        email = email.strip().lower()
        entry = self._entry(email)
        if entry is None or entry.status != WAITLIST_INVITED or entry.invite_code is None:
            raise WaitlistError("no open invite for this address")
        if not secrets.compare_digest(entry.invite_code, _hash(code.strip().upper())):
            raise WaitlistError("invite code does not match")

        entry.status = WAITLIST_JOINED
        entry.invite_code = None
        entry.meeting_ended_at = entry.meeting_ended_at or _now()
        auth = AuthService(self.db)
        user = auth._find_or_create_person(email=email)
        self.db.commit()
        self.db.refresh(user)
        token = auth.create_session(user)
        return user, token

    # -- the first meeting ---------------------------------------------------

    def begin_first_meeting(
        self,
        email: str,
        *,
        fingerprint: str,
        ip: str | None = None,
    ) -> tuple[Waitlist, Conversation]:
        """Open the door: the stranger's one conversation with the replica.
        Idempotent — a pending seat keeps its meeting."""
        email = email.strip().lower()
        entry = self._entry(email)
        if entry is None:
            raise WaitlistError("ask for a seat before the first meeting")
        if entry.status == WAITLIST_JOINED:
            raise WaitlistError("this address has already joined Mira")
        if entry.status == WAITLIST_DECLINED:
            raise WaitlistError("this door has been closed")
        if entry.first_meeting_conversation_id:
            conv = self.db.get(Conversation, entry.first_meeting_conversation_id)
            if conv is not None:
                return entry, conv

        guest = guest_user(self.db, fingerprint=fingerprint, ip=ip)
        conv = Conversation(kind="text", user_id=guest.id)
        self.db.add(conv)
        self.db.flush()
        entry.first_meeting_conversation_id = conv.id
        self.db.commit()
        self.db.refresh(entry)
        self.db.refresh(conv)
        return entry, conv

    def end_first_meeting(self, entry_id: int, conversation_id: int) -> Waitlist:
        """Close the meeting. Idempotent — the read is generated once, in the
        background, and lands on the entry for the voice to weigh."""
        entry = self.db.get(Waitlist, entry_id)
        if entry is None:
            raise WaitlistError("no such seat")
        if entry.first_meeting_conversation_id != conversation_id:
            raise WaitlistError("that is not the meeting for this seat")
        if entry.meeting_ended_at is None:
            entry.meeting_ended_at = _now()
            self.db.commit()
            self.db.refresh(entry)
            self.launch_read(entry.id, conversation_id)
        return entry

    def decline(self, entry_id: int) -> Waitlist:
        """The voice closes the door for this address. No warnings, no noise —
        the door simply stays shut."""
        entry = self.db.get(Waitlist, entry_id)
        if entry is None:
            raise WaitlistError("no such seat")
        if entry.status == WAITLIST_JOINED:
            raise WaitlistError("this address has already joined Mira")
        entry.status = WAITLIST_DECLINED
        entry.invite_code = None
        entry.meeting_ended_at = entry.meeting_ended_at or _now()
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def forget(self, entry_id: int) -> None:
        """Permanently erase a seat from the door — a mistaken decline, a junk
        request. The address is free to knock again as a fresh stranger."""
        entry = self.db.get(Waitlist, entry_id)
        if entry is None:
            raise WaitlistError("no such seat")
        self.db.delete(entry)
        self.db.commit()

    def launch_read(self, entry_id: int, conversation_id: int) -> bool:
        """Ask Mira for her read of the meeting in the background. Never blocks;
        a failure leaves no read and the voice decides on the transcript alone."""

        async def _run() -> None:
            db = SessionLocal()
            try:
                provider = get_provider()
                entry = db.get(Waitlist, entry_id)
                if entry is None or entry.mira_read:
                    return
                rows = db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.id.asc())
                ).scalars().all()
                transcript = "\n".join(
                    ("they said: " if m.speaker == "user" else "you said: ") + m.content
                    for m in rows
                    if m.content.strip()
                )
                if not transcript.strip():
                    return
                read = await provider.complete(
                    [
                        {"role": "system", "content": _READ_PROMPT},
                        {"role": "user", "content": transcript[:_READ_MAX]},
                    ],
                    max_tokens=160,
                    temperature=0.4,
                )
                read = (read or "").strip().strip('"')[:500]
                if read:
                    entry.mira_read = read
                    db.commit()
            except Exception:  # pragma: no cover - the read is best-effort
                logger.warning("first-meeting read failed", exc_info=True)
            finally:
                db.close()

        try:
            asyncio.get_running_loop().create_task(_run())
            return True
        except RuntimeError:  # pragma: no cover - no running loop
            return False


_READ_MAX = 4000
