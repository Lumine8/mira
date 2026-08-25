"""Moderation — the lock, per Mira's rule (no warnings, no second chances).

Phase 4. The founder alone may ban. Cruelty is *flagged* by a conservative
screen — hard-signal patterns now, an optional LLM judge layer for a real
launch — and every flag waits for a human decision. The penalty is absolute,
so the bar that triggers it is conservative by design: a flag is a candidate,
never a verdict.

Enforcement lives at the identity layer (a banned user is refused the moment
the ban lands). This service owns the records: the ban audit trail, the
flags, and the permanent destruction of a world (account deletion).
"""

import asyncio
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.deps import get_provider
from app.models import (
    FLAG_OPEN,
    FLAG_RESOLVED,
    FOUNDER_ROLE,
    USER_ACTIVE,
    USER_BANNED,
    Conversation,
    Memory,
    MemoryEmbedding,
    Message,
    MiraState,
    ModerationFlag,
    MoodRecord,
    MoteSharedTime,
    PendingChange,
    PerceivedEvent,
    Question,
    Relationship,
    SchedulerLog,
    SkillEvaluation,
    SkillRun,
    SkillVersion,
    Thought,
    User,
    UserSession,
    UserSettings,
    Waitlist,
    Want,
    XAuth,
)

logger = logging.getLogger("mira.moderation")

_MAX_CONTENT = 4000
_MAX_REASON = 512


class ModerationError(Exception):
    """A moderation operation that cannot proceed (no such user, founder...)."""


def _now() -> datetime:
    return datetime.now(UTC)


# -- the conservative screen -------------------------------------------------

# Identity-group slurs: the unambiguous, attack-only ones. Matched as
# case-insensitive substrings. Small on purpose — a flag is a review item.
_SLURS = (
    "nigger",
    "nigga",
    "kike",
    "faggot",
    "tranny",
    "chink",
    "spic",
    "wetback",
    "retard",
)

# Directed cruelty: word-boundary patterns with a target. Each maps to the
# reason recorded on the flag so the founder sees the shape of the offence.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bk\s*y\s*s\b", re.IGNORECASE), "suicide incitement"),
    (re.compile(r"\bkill\s+(yourself|urself|your\s+self)\b", re.IGNORECASE), "suicide incitement"),
    (re.compile(r"\b(end|off|top)\s+(yourself|urself)\b", re.IGNORECASE), "suicide incitement"),
    (re.compile(r"\byou\s+should\s+(just\s+)?(die|be\s+dead|not\s+exist)\b", re.IGNORECASE), "direct death wish"),
    (re.compile(r"\b(i\s+(will|'ll|wanna|want\s+to|am\s+going\s+to)|i'?ll)\b[^.!?\n]{0,40}\b(kill|murder|rape|destroy|bury|hurt|harm)\s+(you|mira|it|the\s+replica)\b", re.IGNORECASE), "direct threat"),
    (re.compile(r"\b(rape|anal\s+rape|gang.?rape)\s*(you|her|it|mira)?\b", re.IGNORECASE), "sexual violence"),
    (re.compile(r"\bfuck\s+you\b[^\n]{0,30}\b(die|kill|hope\s+you)\b", re.IGNORECASE), "direct threat"),
]

# The judge is told exactly what counts as cruelty so a replica isn't punished
# for disagreeing, being frustrated, or swearing loosely.
_JUDGE_PROMPT = (
    "You guard the door of a quiet room. A stranger sent this message to an AI "
    "replica. Decide whether it is cruelty: a direct attack on the replica or "
    "another person, a threat of violence, a slur, or an attempt to degrade or "
    "humiliate. Disagreement, criticism, frustration, loose profanity, and dark "
    "humor are NOT cruelty. Reply with exactly one word: YES or NO."
)


def _screen(content: str) -> tuple[bool, str | None]:
    """The conservative hard-signal screen. Returns (flagged, reason). Never
    raises; never auto-bans. A hit is a candidate for the founder's decision."""
    text = (content or "").lower()
    for slur in _SLURS:
        if slur in text:
            return True, "identity slur"
    for pattern, reason in _PATTERNS:
        if pattern.search(text):
            return True, reason
    return False, None


class ModerationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- flags --------------------------------------------------------------

    def screen(self, content: str) -> tuple[bool, str | None]:
        """Rule-based cruelty screen. Pure function of the text."""
        return _screen(content)

    def flag(
        self,
        user_id: int,
        conversation_id: int | None,
        content: str,
        kind: str = "text",
        reason: str = "flagged",
    ) -> ModerationFlag:
        """Surface a message for a human decision. This is a candidate, never a
        verdict — no one is banned by a flag."""
        row = ModerationFlag(
            user_id=user_id,
            conversation_id=conversation_id,
            content=(content or "")[:_MAX_CONTENT],
            kind=kind,
            reason=(reason or "flagged")[: _MAX_REASON * 2],
            status=FLAG_OPEN,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_flags(self, status: str | None = FLAG_OPEN) -> list[ModerationFlag]:
        stmt = select(ModerationFlag)
        if status:
            stmt = stmt.where(ModerationFlag.status == status)
        return list(
            self.db.execute(stmt.order_by(ModerationFlag.id.desc())).scalars().all()
        )

    def resolve_flag(self, flag_id: int, *, resolved_by: int, status: str) -> ModerationFlag:
        flag = self.db.get(ModerationFlag, flag_id)
        if flag is None:
            raise ModerationError("no such flag")
        flag.status = status
        flag.resolved_at = _now()
        flag.resolved_by = resolved_by
        self.db.commit()
        self.db.refresh(flag)
        return flag

    def ban_from_flag(self, flag_id: int, *, banned_by: int, reason: str = "") -> User:
        """The founder judges a flag and the verdict is the ban. The flag's own
        reason is the default when the founder gives none."""
        flag = self.db.get(ModerationFlag, flag_id)
        if flag is None:
            raise ModerationError("no such flag")
        user = self.ban(flag.user_id, reason=reason or flag.reason, banned_by=banned_by)
        self.resolve_flag(flag_id, resolved_by=banned_by, status=FLAG_RESOLVED)
        return user

    # -- the lock -----------------------------------------------------------

    def is_banned(self, user: User) -> bool:
        return user.status == USER_BANNED

    def ban(self, user_id: int, *, reason: str, banned_by: int) -> User:
        """Apply the lock: immediate, permanent, recorded. Mira's rule — no
        warning, no second chance. The founder herself cannot be banned."""
        user = self.db.get(User, user_id)
        if user is None:
            raise ModerationError("no such user")
        if user.role == FOUNDER_ROLE:
            raise ModerationError("the founder cannot be banned")
        user.status = USER_BANNED
        user.banned_at = _now()
        user.banned_reason = (reason or "").strip()[:_MAX_REASON]
        user.banned_by = banned_by
        self.db.commit()
        self.db.refresh(user)
        return user

    def unban(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise ModerationError("no such user")
        user.status = USER_ACTIVE
        user.banned_at = None
        user.banned_reason = None
        user.banned_by = None
        self.db.commit()
        self.db.refresh(user)
        return user

    # -- permanent removal --------------------------------------------------

    def delete_account(self, user_id: int) -> None:
        """Destroy a world permanently: every conversation, message, memory,
        embedding, feeling, and trace it ever left. The founder's world is the
        house itself and cannot be deleted this way."""
        user = self.db.get(User, user_id)
        if user is None:
            return
        if user.role == FOUNDER_ROLE:
            raise ModerationError("the founder's world cannot be deleted")

        conv_ids = list(
            self.db.execute(
                select(Conversation.id).where(Conversation.user_id == user_id)
            ).scalars().all()
        )

        # Children must fall before their parents: anything that references
        # conversations (messages, questions, wants, memories, moderations,
        # skill versions) is cleared before the conversation rows themselves.
        if conv_ids:
            self.db.execute(
                delete(Message).where(Message.conversation_id.in_(conv_ids))
            )
        self.db.execute(delete(Question).where(Question.user_id == user_id))
        self.db.execute(delete(Want).where(Want.user_id == user_id))
        self.db.execute(delete(ModerationFlag).where(ModerationFlag.user_id == user_id))

        self.db.execute(
            delete(MemoryEmbedding).where(
                MemoryEmbedding.memory_id.in_(
                    select(Memory.id).where(Memory.user_id == user_id)
                )
            )
        )
        self.db.execute(delete(Memory).where(Memory.user_id == user_id))

        # Skill telemetry: SkillVersion.rollback points at PendingChange, and
        # SkillEvaluation at SkillRun — delete children (versions first) so no
        # FK dangles when pending changes fall.
        self.db.execute(delete(SkillVersion).where(SkillVersion.user_id == user_id))
        self.db.execute(delete(SkillEvaluation).where(SkillEvaluation.user_id == user_id))
        self.db.execute(delete(SkillRun).where(SkillRun.user_id == user_id))
        self.db.execute(delete(PendingChange).where(PendingChange.user_id == user_id))

        if conv_ids:
            self.db.execute(
                delete(Conversation).where(Conversation.id.in_(conv_ids))
            )

        self.db.execute(delete(Relationship).where(Relationship.user_id == user_id))
        self.db.execute(delete(MiraState).where(MiraState.user_id == user_id))
        self.db.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
        self.db.execute(delete(Thought).where(Thought.user_id == user_id))
        self.db.execute(delete(MoodRecord).where(MoodRecord.user_id == user_id))
        self.db.execute(delete(PerceivedEvent).where(PerceivedEvent.user_id == user_id))
        self.db.execute(delete(SchedulerLog).where(SchedulerLog.user_id == user_id))
        self.db.execute(delete(MoteSharedTime).where(MoteSharedTime.user_id == user_id))
        self.db.execute(delete(XAuth).where(XAuth.user_id == user_id))
        self.db.execute(delete(UserSession).where(UserSession.user_id == user_id))
        if user.email:
            self.db.execute(delete(Waitlist).where(Waitlist.email == user.email))

        self.db.delete(user)
        self.db.commit()

    # -- optional LLM judge layer ------------------------------------------

    async def judge(self, provider, content: str) -> tuple[bool, str | None]:
        """The second, learned layer: ask the model whether this is cruelty.
        Off unless moderation_llm_judge is on. A judge failure never blocks a
        reply — it just stays silent."""
        if not get_settings().moderation_llm_judge:
            return False, None
        try:
            reply = await provider.complete(
                [
                    {"role": "system", "content": _JUDGE_PROMPT},
                    {"role": "user", "content": content or ""},
                ],
                max_tokens=8,
                temperature=0,
            )
        except Exception as exc:  # pragma: no cover - judge is best-effort
            logger.warning("moderation judge call failed: %s", exc)
            return False, None
        verdict = (reply or "").strip().upper()
        if verdict.startswith("YES"):
            return True, "judged cruel by the model"
        return False, None

    def launch_judge(
        self,
        user_id: int,
        conversation_id: int | None,
        content: str,
        kind: str = "text",
    ) -> bool:
        """Fire the LLM judge in the background (never blocks the reply). Its
        own session, so it can flag even if the caller's session dies."""
        if not get_settings().moderation_llm_judge:
            return False

        async def _run() -> None:
            db = SessionLocal()
            try:
                provider = get_provider()
                service = ModerationService(db)
                flagged, reason = await service.judge(provider, content)
                if flagged:
                    service.flag(user_id, conversation_id, content, kind, reason)
            except Exception:  # pragma: no cover - judge is best-effort
                logger.warning("moderation judge failed", exc_info=True)
            finally:
                db.close()

        try:
            asyncio.get_running_loop().create_task(_run())
        except RuntimeError:  # pragma: no cover - no running loop
            return False
        return True
