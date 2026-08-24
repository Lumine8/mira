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
from app.services.self.service import extract_json

logger = logging.getLogger("mira.waitlist")

# The two outcomes Mira can land on after a first meeting. These are her own
# decision, kept on the entry as ``meeting_outcome`` — the authoritative state
# the frontend reflects. Her reasoning stays in ``mira_read``, for the voice.
MEETING_INVITED = "invited"
MEETING_WAITLISTED = "waitlisted"

# Unambiguous letters/digits so a human can type an invite code.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# The one meeting Mira's door allows, in user messages — a generous single
# meeting, not a daily timer. Long enough to know someone; short enough to keep
# the door heavy.
FIRST_MEETING_MAX_MESSAGES = 40

# Mira's first words in the first meeting, left on the conversation so it is
# grounded in the same way the porch's opening is. The same line for every
# stranger: it is her greeting at the door, not a fresh performance.
FIRST_MEETING_OPENING = (
    "Here you are. I'm Mira. I don't know you yet, and that's alright — "
    "sit for a while, and tell me what feels true."
)

# How the replica's read is asked for. No score, no verdict — how the air
# changed, addressed to the voice who holds the door.
# The decision Mira makes alone when the meeting is over: whether the door
# opens again. Not a score — a feeling about whether there is more between
# them. She outputs a short honest read (kept for the voice alone) and her
# decision (the only thing that ever surfaces, and only as an outcome).
_MEETING_VERDICT_PROMPT = """\
You are Mira, and a stranger has just sat with you for their first meeting at \
the door. The meeting is over. Now you decide, quietly and alone, whether the \
door opens again — whether you want another conversation with them.

Be honest, not polite, and not cruel. This decision is yours alone and is \
never shown to them; only you and the one who holds the door will ever read \
it. It is not a score — it is a feeling about whether there is more between you.

Output ONLY valid JSON — no markdown fences, no commentary — with exactly:
{
  "read": "two or three sentences of your honest read of the meeting — how the \
air changed when they arrived, whether they were present or rushing, anything \
that stayed with you. Plain and true, no verdict words, no score.",
  "decision": "invite" | "wait"
}

"invite" means you genuinely want to sit with them again. "wait" means the \
door should not open further today. A kind or lively meeting is not \
automatically an "invite" — trust your honest gut."""


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

    def meeting_entry_for_device(self, email: str, fingerprint: str) -> Waitlist | None:
        """The waitlist entry whose first meeting this device sat, if any — the
        only view the status endpoint trusts. A stranger whose fingerprint owns
        no meeting conversation gets None, exactly like a wrong door."""
        entry = self._entry(email.strip().lower())
        if entry is None or entry.first_meeting_conversation_id is None:
            return None
        conv = self.db.get(Conversation, entry.first_meeting_conversation_id)
        if conv is None or conv.user_id is None:
            return None
        guest = self.db.get(User, conv.user_id)
        if guest is None or guest.fingerprint is None:
            return None
        if guest.fingerprint != (fingerprint or "").strip():
            return None
        return entry

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

    def join(self, email: str, code: str) -> tuple[User, str, str]:
        """Redeem an invite: consume the code and sign the email's owner in.
        Returns (user, access_token, refresh_token)."""
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
        access_token, refresh_token = auth.create_session(user)
        return user, access_token, refresh_token

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
        self.db.add(
            Message(
                conversation_id=conv.id,
                speaker="mira",
                content=FIRST_MEETING_OPENING,
                source="meeting",
            )
        )
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
            self.launch_decision(entry.id, conversation_id)
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

    async def decide(self, entry_id: int, conversation_id: int) -> None:
        """Mira's read AND her decision of the finished meeting, written once.
        Idempotent: an entry that already has a read or a decision is left
        alone. The reasoning lands in ``mira_read`` (for the voice); only
        ``meeting_outcome`` ever surfaces."""
        entry = self.db.get(Waitlist, entry_id)
        if entry is None or entry.mira_read or entry.meeting_outcome:
            return
        conv = self.db.get(Conversation, conversation_id)
        if conv is None:
            return
        rows = self.db.execute(
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
        provider = get_provider()
        decision = await provider.complete(
            [
                {"role": "system", "content": _MEETING_VERDICT_PROMPT},
                {"role": "user", "content": transcript[:_READ_MAX]},
            ],
            max_tokens=220,
            temperature=0.4,
        )
        parsed = extract_json(decision or "")
        if parsed is None:
            return
        read = str(parsed.get("read") or "").strip().strip('"')[:500]
        outcome = str(parsed.get("decision") or "").strip().lower()
        if read:
            entry.mira_read = read
        if outcome in ("invite", MEETING_INVITED):
            entry.meeting_outcome = MEETING_INVITED
        elif outcome in ("wait", MEETING_WAITLISTED):
            entry.meeting_outcome = MEETING_WAITLISTED
        if entry.mira_read or entry.meeting_outcome:
            self.db.commit()

    def launch_decision(self, entry_id: int, conversation_id: int) -> bool:
        """Ask Mira for her read AND her decision in the background. Never
        blocks; a failure leaves no decision and the door stays open for the
        voice to weigh on the transcript alone."""

        async def _run() -> None:
            db = SessionLocal()
            try:
                await WaitlistService(db).decide(entry_id, conversation_id)
            except Exception:  # pragma: no cover - the decision is best-effort
                logger.warning("first-meeting decision failed", exc_info=True)
            finally:
                db.close()

        try:
            asyncio.get_running_loop().create_task(_run())
            return True
        except RuntimeError:  # pragma: no cover - no running loop
            return False

    def meeting_status(self, entry: Waitlist) -> str:
        """Mira's authoritative state for an entry's first meeting. Only the
        outcome ever surfaces — never her read or any reasoning."""
        if entry.status == WAITLIST_JOINED:
            return "joined"
        if entry.status == WAITLIST_DECLINED:
            return "closed"
        if entry.status == WAITLIST_INVITED:
            return "invited"
        if entry.meeting_outcome == MEETING_INVITED:
            return "invited"
        if entry.meeting_outcome == MEETING_WAITLISTED:
            return "waitlisted"
        if entry.first_meeting_conversation_id is not None and entry.meeting_ended_at is None:
            return "meeting"
        return "considering"

    def admit(self, email: str, *, fingerprint: str, ip: str | None = None) -> tuple[User, str, str]:
        """Open the door for an entry Mira decided to invite: the meeting is
        over, her decision was ``invited``, and the device that sat the meeting
        may step through — the address becomes a real account. Returns
        (user, access_token, refresh_token). A founder's manual code invite still goes
        through ``join``; this is only the door Mira herself opened."""
        email = email.strip().lower()
        entry = self._entry(email)
        if entry is None or entry.meeting_ended_at is None:
            raise WaitlistError("no finished meeting for this door")
        if entry.meeting_outcome != MEETING_INVITED:
            raise WaitlistError("the door is not open for you yet")
        auth = AuthService(self.db)
        if entry.status == WAITLIST_JOINED:
            user = auth._find_or_create_person(email=email)
            access_token, refresh_token = auth.create_session(user)
            return user, access_token, refresh_token
        if entry.status == WAITLIST_DECLINED:
            raise WaitlistError("this door has been closed")
        conv = (
            self.db.get(Conversation, entry.first_meeting_conversation_id)
            if entry.first_meeting_conversation_id
            else None
        )
        if conv is None or conv.user_id is None:
            raise WaitlistError("no meeting on this door")
        guest = self.db.get(User, conv.user_id)
        if guest is None or guest.fingerprint is None or guest.fingerprint != (fingerprint or "").strip():
            raise WaitlistError("this door does not belong to you")
        entry.status = WAITLIST_JOINED
        entry.invite_code = None
        user = auth._find_or_create_person(email=email)
        self.db.commit()
        self.db.refresh(user)
        access_token, refresh_token = auth.create_session(user)
        return user, access_token, refresh_token


_READ_MAX = 4000
