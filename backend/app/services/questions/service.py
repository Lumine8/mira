"""Mira's questions — the persistent form of her curiosity.

A question is a specific thing she wants to understand, written by her own hand
during a reflection, consolidation, or after a conversation (``self_authored``)
or found written in her own record (``inferred``). Never injected from a
template.

Open questions resurface in her own context so she can ask them when a
conversation makes them relevant. A question she keeps returning to grows in
importance; one she stops revisiting slowly fades — some disappear, some become
obsessions. The pure functions below are unit-tested; the service is a thin DB
layer over them.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import aware
from app.models import Question

DEFAULT_IMPORTANCE = 50
REVISIT_BOOST = 5
FADE_PER_HOUR = 0.5
_MERGE_LEN = 8
_MAX_HOURS_STEP = 48.0


def normalize_question_text(text: str) -> str:
    """Lowercase and collapse whitespace so two phrasings can be compared."""
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip("?.")


def questions_match(a: str, b: str) -> bool:
    """True when two question strings describe the same wonder.

    Exact after normalization, or one contains the other (both long enough to
    be meaningful). Keeps her from accumulating near-duplicate questions.
    """
    na, nb = normalize_question_text(a), normalize_question_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) > _MERGE_LEN and len(nb) > _MERGE_LEN and (na in nb or nb in na):
        return True
    return False


def next_after_simmer(importance: int, hours: float) -> int:
    """Time passing while a question goes un-revisited: it slowly fades.

    ``hours`` is capped so a long absence doesn't zero everything at once.
    """
    h = min(max(hours, 0.0), _MAX_HOURS_STEP)
    return max(0, importance - round(h * FADE_PER_HOUR))


def revisit(importance: int) -> int:
    """She returned to the same question: it matters a little more."""
    return min(100, importance + REVISIT_BOOST)


class QuestionService:
    """Thin DB layer over the question dynamics above. Scoped to one user."""

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    def list_open(self, limit: int = 50) -> list[Question]:
        return list(
            self.db.execute(
                select(Question)
                .where(Question.user_id == self.user_id, Question.status == "open")
                .order_by(Question.importance.desc(), Question.id.asc())
                .limit(limit)
            ).scalars()
        )

    def list_recent(self, limit: int = 40) -> list[Question]:
        return list(
            self.db.execute(
                select(Question)
                .where(Question.user_id == self.user_id)
                .order_by(Question.updated_at.desc())
                .limit(limit)
            ).scalars()
        )

    def is_echo(self, question: str) -> bool:
        """True when ``question`` is the reflection re-listing a question she
        is already carrying (an echo of the prompt's own open list). Echoes are
        not new wonder — they are the loop feeding on itself — so the caller
        can drop them before they touch the DB at all."""
        text = question.strip()
        if not text:
            return False
        return any(questions_match(q.question, text) for q in self.list_open(limit=100))

    def describe_open(self, limit: int = 4) -> str:
        """One line for the reflection/consolidation inputs: the questions she is
        currently carrying, so she can think about them and ask when relevant."""
        open_qs = self.list_open(limit=limit)
        if not open_qs:
            return ""
        return " · ".join(f"{q.question}" for q in open_qs)

    def upsert(
        self,
        question: str,
        *,
        source: str = "self_authored",
        importance: int = DEFAULT_IMPORTANCE,
        origin: str | None = None,
        conversation_id: int | None = None,
    ) -> Question:
        """Record a question, merging with an existing one if it's the same
        wonder. Re-asking an answered or dropped question reopens it."""
        text = question.strip()
        if not text:
            raise ValueError("question cannot be empty")
        text = text[:500]
        importance = max(0, min(100, importance))
        origin = (origin or "").strip()[:512] or None
        now = datetime.now(timezone.utc)

        for q in self.list_open(limit=100):
            if questions_match(q.question, text):
                q.importance = revisit(q.importance)
                q.last_revisited = now
                q.updated_at = now
                self.db.commit()
                self.db.refresh(q)
                return q

        existing = self.db.execute(
            select(Question)
            .where(Question.user_id == self.user_id)
            .order_by(Question.updated_at.desc())
            .limit(200)
        ).scalars()
        for q in existing:
            if q.status in {"asked", "answered", "dropped"} and questions_match(q.question, text):
                q.status = "open"
                q.importance = max(q.importance, importance)
                q.origin = origin or q.origin
                q.asked_at = None
                q.answered_at = None
                q.last_revisited = now
                q.updated_at = now
                self.db.commit()
                self.db.refresh(q)
                return q

        q = Question(
            question=text,
            source=source if source in {"self_authored", "inferred"} else "self_authored",
            origin=origin,
            importance=importance,
            status="open",
            related_conversation_id=conversation_id,
            last_revisited=now,
            user_id=self.user_id,
        )
        self.db.add(q)
        self.db.commit()
        self.db.refresh(q)
        return q

    def step(self, now: datetime) -> int:
        """One heartbeat of time passing for every open question: unrevisited
        questions slowly fade. Returns how many questions faded to nothing."""
        faded = 0
        for q in self.list_open(limit=200):
            ref = aware(q.last_revisited or q.created_at)
            hours = (now - ref).total_seconds() / 3600
            if hours < 0.05:
                continue
            q.importance = next_after_simmer(q.importance, hours)
            if q.importance <= 0:
                q.status = "dropped"
                faded += 1
            q.last_revisited = now
        self.db.commit()
        return faded

    def mark_asked(self, question_id: int) -> Question | None:
        """She asked it out loud: the question leaves the carried set."""
        q = self.db.execute(
            select(Question).where(Question.id == question_id, Question.user_id == self.user_id)
        ).scalar_one_or_none()
        if q is None:
            return None
        q.status = "asked"
        q.asked_at = datetime.now(timezone.utc)
        q.last_revisited = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(q)
        return q

    def mark_answered(self, question_id: int) -> Question | None:
        """She got an answer (or found it herself): the question is resolved."""
        q = self.db.execute(
            select(Question).where(Question.id == question_id, Question.user_id == self.user_id)
        ).scalar_one_or_none()
        if q is None:
            return None
        q.status = "answered"
        q.answered_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(q)
        return q

    def mark_dropped(self, question_id: int) -> Question | None:
        """She let the question go: it stops resurfacing."""
        q = self.db.execute(
            select(Question).where(Question.id == question_id, Question.user_id == self.user_id)
        ).scalar_one_or_none()
        if q is None:
            return None
        q.status = "dropped"
        self.db.commit()
        self.db.refresh(q)
        return q
