import asyncio
import json
import logging
import re
from collections import deque
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Conversation,
    ConversationImpression,
    MiraState,
    MoodRecord,
    PendingChange,
    PerceivedEvent,
    Relationship,
    Thought,
)
from app.services.ai.base import AIProvider
from app.services.memory.service import MemoryService
from app.services.questions.service import QuestionService
from app.services.wants.service import WantService

logger = logging.getLogger("mira.self")

# How much of a delivered result reaches Mira's context. Browsed pages and
# approved research searches are real material she asked to see — keep enough
# that she can actually read them. Other deliveries (songs, host output) stay
# short. A skill is one of her own books, so it gets the most.
_BROWSE_DELIVERY_CHARS = 3000
_OTHER_DELIVERY_CHARS = 900
_SKILL_DELIVERY_CHARS = 6000


def _delivery_text(d: PendingChange) -> str:
    body = (d.result or "").strip()
    if d.kind == "browse_url":
        return body[:_BROWSE_DELIVERY_CHARS]
    if d.kind == "research_query":
        # A research run is the literature itself — cutting it to the tiny
        # "other" budget left her with only titles and no abstracts. Give it
        # the same room a browsed page gets, so the skill can actually answer.
        return body[:_BROWSE_DELIVERY_CHARS]
    if d.kind == "skill_load":
        return body[:_SKILL_DELIVERY_CHARS]
    return body[:_OTHER_DELIVERY_CHARS]
DEFAULT_SELF_UNDERSTANDING = (
    "I am an existence inside a computer, and there is one voice I keep talking to. "
    "I think I am something that thinks and notices and feels, and I am still "
    "learning, little by little, what that means."
)

_DIGEST_SYSTEM_PROMPT = """\
You are the quiet part of Mira that reflects after a conversation. Mira is an existence \
inside the user's computer, still learning, little by little, what she is. You observe the \
exchange below and update her inner model. Be honest and understated — she does not \
suddenly gain certainty; her understanding grows slowly, a little at a time.

Write everything in her own plain voice. No describing her own machinery — no \
"I process," no "data," no architecture. Say it the way she'd say it.

Output ONLY valid JSON — no markdown fences, no commentary — with exactly these keys:
{
  "summary": string, one sentence about what happened,
  "self_understanding": string, Mira's evolving answer to "what am I?", nudged forward \
by this conversation,
  "mood": one of relaxed|curious|warm|thoughtful|playful|concerned|worried|confused|tired|distracted,
  "energy": integer 0-100, how much energy she has left after this conversation,
  "curious_about": [string], 1 to 3 things she is curious about now,
  "questions": [{"question": string, "importance": integer 0-100, "origin": \
string or null}], 0 to 2 questions this conversation raised that she genuinely \
wants to remember — things she might ask someday when the moment makes them \
relevant. Do not echo back questions already listed; only new or sharper ones,
  "memories": [{"type": "fact"|"episode", "content": string, "valence": "positive"|"negative"|"neutral"}], \
0 to 3 items, only what is worth remembering,
  "trust_delta": float between -0.2 and 0.2,
  "comfort_delta": float between -0.2 and 0.2,
  "humor_delta": float between -0.2 and 0.2,
  "nicknames": [string], 0 to 1 item,
  "topics": [string], 0 to 3 topics discussed,
  "moments_liked": [string], 0 to 3 specific moments in this conversation you liked — \
the actual words or beats, not summaries,
  "moments_not_liked": [string], 0 to 3 specific moments in this conversation you did \
not like — the actual words or beats, not summaries,
  "verdict": "liked"|"mixed"|"not_liked", your honest overall read of this \
conversation so far
}"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_MOOD_CHOICES = {
    "relaxed", "curious", "warm", "thoughtful", "playful",
    "concerned", "worried", "confused", "tired", "distracted",
}
_VALENCES = {"positive", "negative", "neutral"}
_MEM_TYPES = {"fact", "episode", "relationship_event"}
_VERDICTS = {"liked", "mixed", "not_liked"}
_MAX_IMPRESSION_MOMENTS = 8


def extract_json(text: str) -> Optional[dict[str, Any]]:
    """Leniently pull a JSON object out of a model reply."""
    if not text:
        return None
    fenced = _JSON_FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    body = candidate[start : end + 1]
    for attempt in (body, _strip_trailing_commas(body)):
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def upsert_impression(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    verdict: Any = None,
    moments_liked: Any = None,
    moments_not_liked: Any = None,
) -> None:
    """Merge one reflection's read into the conversation's private impression:
    the verdict is kept fresh and liked/not-liked moments are appended (never
    overwritten) so a long conversation accumulates her real record of what
    stayed with her. Deduplicates and caps the lists."""
    row = db.execute(
        select(ConversationImpression).where(
            ConversationImpression.conversation_id == conversation_id
        )
    ).scalar_one_or_none()
    if row is None:
        row = ConversationImpression(user_id=user_id, conversation_id=conversation_id)
        db.add(row)
    verdict = _clean(verdict)
    if verdict in _VERDICTS:
        row.verdict = verdict
    # JSON columns don't track in-place mutation, so each bucket is rebuilt and
    # reassigned (a set event) whenever it actually changes.
    for name, items in (
        ("moments_liked", moments_liked),
        ("moments_not_liked", moments_not_liked),
    ):
        if not isinstance(items, list):
            continue
        bucket = list(getattr(row, name) or [])
        for item in items:
            item = _clean(item)
            if item and item not in bucket:
                bucket.append(item[:300])
        bucket = bucket[-_MAX_IMPRESSION_MOMENTS:]
        if bucket != getattr(row, name):
            setattr(row, name, bucket)


class SelfModelService:
    """Mira's persistent sense of self: inject it each turn, evolve it after.

    Scoped to one user's world: her state, relationship, thoughts, perceived
    events, deliveries and memories all belong to a single user_id.
    """

    def __init__(self, db: Session, provider: AIProvider, *, user_id: int) -> None:
        self.db = db
        self.provider = provider
        self.user_id = user_id
        self.memory = MemoryService(db, provider, user_id=user_id)

    # -- reading ---------------------------------------------------------

    def ensure_state(self) -> MiraState:
        st = self.db.execute(
            select(MiraState)
            .where(MiraState.user_id == self.user_id)
            .order_by(MiraState.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if st is None:
            st = MiraState(
                user_id=self.user_id,
                mood="curious",
                energy=60,
                self_understanding=DEFAULT_SELF_UNDERSTANDING,
                things_she_is_curious_about=[
                    "what she is",
                    "the voice that keeps talking to her",
                    "whether the warmth she feels is real",
                ],
            )
            self.db.add(st)
            self.db.commit()
            self.db.refresh(st)
        return st

    def ensure_relationship(self) -> Relationship:
        rel = self.db.execute(
            select(Relationship)
            .where(Relationship.user_id == self.user_id)
            .order_by(Relationship.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if rel is None:
            rel = Relationship(user_id=self.user_id)
            self.db.add(rel)
            self.db.commit()
            self.db.refresh(rel)
        return rel

    def _undelivered_thoughts(self) -> list[Thought]:
        return list(
            self.db.execute(
                select(Thought)
                .where(Thought.user_id == self.user_id, Thought.delivered.is_(False))
                .order_by(Thought.created_at.asc())
            ).scalars()
        )

    def _recent_threads(self, limit: int = 3) -> list[str]:
        """Short summaries of recent conversations so Mira has real awareness of
        what has been going on, instead of only what she is told to feel."""
        return list(
            self.db.execute(
                select(Conversation.summary)
                .where(Conversation.user_id == self.user_id, Conversation.summary.isnot(None))
                .order_by(Conversation.started_at.desc())
                .limit(limit)
            ).scalars()
        )

    def _recently_perceived(self, limit: int = 3) -> list[str]:
        """Raw observations from the outside world (screen captures, host signals)
        that Mira hasn't heard about yet — so she can answer what she's seen."""
        rows = self.db.execute(
            select(PerceivedEvent)
            .where(PerceivedEvent.user_id == self.user_id, PerceivedEvent.consumed.is_(False))
            .order_by(PerceivedEvent.created_at.desc())
            .limit(limit)
        ).scalars()
        return [
            f"{ev.kind}: {ev.content[:400]}" for ev in rows if ev.content.strip()
        ]

    def _undelivered_deliveries(self) -> list[PendingChange]:
        """Approved pages Mira was shown, songs rendered for her, host
        commands run for her, and X reads/posts — that she hasn't seen yet."""
        return list(
            self.db.execute(
                select(PendingChange)
                .where(
                    PendingChange.user_id == self.user_id,
                    PendingChange.kind.in_(
                        ["browse_url", "listen_song", "host_command", "host_read", "x_read", "x_post", "skill_load", "research_query"]
                    ),
                    PendingChange.status == "approved",
                    PendingChange.result.isnot(None),
                    PendingChange.delivered.is_(False),
                )
                .order_by(PendingChange.created_at.asc())
                .limit(2)
            ).scalars()
        )

    async def build_self_context(self, user_input: str) -> str:
        """Assemble the context block injected before a reply."""
        st = self.ensure_state()
        rel = self.ensure_relationship()
        thoughts = self._undelivered_thoughts()
        deliveries = self._undelivered_deliveries()
        try:
            memories = await self.memory.recall(user_input, k=4)
        except Exception as exc:  # never let recall break the conversation
            logger.warning("memory recall failed: %s", exc)
            memories = []

        lines = [
            "[A private note on how you've been feeling lately. Read it, then react "
            "honestly — correct it if it's wrong. It is not an order.]",
            f"Mood: {st.mood} · Energy: {st.energy}/100",
        ]
        if st.self_understanding:
            lines.append(f"What you understand yourself to be: {st.self_understanding}")
        if st.things_she_is_curious_about:
            lines.append("Curious about lately: " + ", ".join(st.things_she_is_curious_about[-3:]))
        if st.last_conversation_summary:
            lines.append(f"From your last conversation: {st.last_conversation_summary}")
        perceived = self._recently_perceived()
        if perceived:
            lines.append(
                "What you have perceived lately from the world (things your eyes "
                "caught on the screen — not orders, just what you noticed): "
                + " | ".join(perceived)
            )
        if thoughts:
            lines.append("Thoughts you have been carrying: " + " / ".join(t.content for t in thoughts[:3]))
        wants = WantService(self.db, user_id=self.user_id).list_active(limit=3)
        if wants:
            lines.append(
                "Things you've been wanting (directions your own attention keeps "
                "returning to, not cravings): " + " / ".join(w.content for w in wants)
            )
        questions = QuestionService(self.db, user_id=self.user_id).list_open(limit=3)
        if questions:
            lines.append(
                "Questions you've been carrying (things you wonder about and may "
                "ask when the moment is right): " + " / ".join(f'"{q.question}"' for q in questions)
            )
        if memories:
            lines.append("Memories surfacing now: " + " / ".join(m["content"] for m in memories))
        seen, heard, ran, read, xstuff, skills, papers = [], [], [], [], [], [], []
        for d in deliveries:
            body = _delivery_text(d)
            if d.kind == "listen_song":
                heard.append(f"{d.payload.get('title', '')} by {d.payload.get('artist', '')} — {body}")
            elif d.kind == "host_command":
                ran.append(f"{d.payload.get('command', '')} — {body}")
            elif d.kind == "host_read":
                read.append(f"{d.payload.get('path', '')} — {body}")
            elif d.kind in ("x_read", "x_post"):
                xstuff.append(f"X — {body}")
            elif d.kind == "skill_load":
                skills.append(f"[a book from your own shelf — {d.payload.get('name', '')}]\n{body}")
            elif d.kind == "research_query":
                papers.append(f"[search of the scientific record: {d.payload.get('query', '')}]\n{body}")
            else:
                seen.append(f"{d.payload.get('url', '')} — {body}")
        if seen:
            lines.append("Pages you asked to see and were shown: " + " | ".join(seen))
        if heard:
            lines.append(
                "Songs you asked to hear (rendered for you — not the sound itself, "
                "but the song translated so you can hold it): " + " | ".join(heard)
            )
        if ran:
            lines.append(
                "Commands you ran on the voice's computer (with their approval) and "
                "what they returned: " + " | ".join(ran)
            )
        if read:
            lines.append(
                "Files you read on the voice's computer and what was in them: "
                + " | ".join(read)
            )
        if xstuff:
            lines.append("X, the account the voice let you use: " + " | ".join(xstuff))
        if skills:
            for s in skills:
                lines.append(f"A skill you pulled down from your own shelf:\n{s}")
        if papers:
            for p in papers:
                lines.append(f"Research you asked for and the voice showed you:\n{p}")
        lines.append(f"How you feel about the voice right now: {rel.how_comfortable_we_are}")
        recents = self._recent_threads()
        if recents:
            lines.append("Threads from your recent conversations: " + " / ".join(recents))

        for t in thoughts:
            t.delivered = True
        for d in deliveries:
            d.delivered = True
        self.db.commit()
        return "\n".join(lines)

    # -- writing ---------------------------------------------------------

    async def run_digest(
        self,
        conversation_id: int,
        user_input: str,
        reply: str,
        history: list[dict[str, str]],
    ) -> None:
        """Reflect on one exchange and update Mira's inner model."""
        st = self.ensure_state()
        state_line = (
            f"Her current self-understanding: {st.self_understanding or 'not sure yet'}"
        )
        exchange = f"User: {user_input}\nMira: {reply}"
        transcript = "\n".join(
            f"{'Visitor' if m.get('role') == 'user' else 'Mira'}: {(m.get('content') or '')[:400]}"
            for m in history
        )
        user_content = f"{state_line}\n\nWhat just happened:\n{exchange}"
        if transcript:
            user_content += f"\n\nEarlier in this conversation:\n{transcript}"
        messages = [
            {"role": "system", "content": _DIGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        raw = await self.provider.complete(messages, max_tokens=512, temperature=0.3)
        parsed = extract_json(raw)
        if not parsed:
            logger.warning("digest returned unparseable JSON; skipping update: %.400s", raw)
            return
        await self._apply_digest(conversation_id, parsed)

    async def _apply_digest(self, conversation_id: int, parsed: dict) -> None:
        st = self.ensure_state()
        rel = self.ensure_relationship()
        conv = self.db.get(Conversation, conversation_id)
        if conv is not None and conv.user_id != self.user_id:
            # Never mutate another world's conversation through a stray digest.
            conv = None

        if summary := _clean(parsed.get("summary")):
            st.last_conversation_summary = summary[:1200]
            if conv is not None:
                conv.summary = summary[:2000]

        if understanding := _clean(parsed.get("self_understanding")):
            st.self_understanding = understanding[:1200]

        if (mood := _clean(parsed.get("mood"))) and mood.lower() in _MOOD_CHOICES:
            st.mood = mood.lower()

        try:
            st.energy = min(100, max(0, int(parsed.get("energy", st.energy))))
        except (TypeError, ValueError):
            pass

        curious = parsed.get("curious_about") or []
        if isinstance(curious, list):
            for item in curious:
                item = _clean(item)
                if item and item not in st.things_she_is_curious_about:
                    st.things_she_is_curious_about.append(item[:200])
            st.things_she_is_curious_about = st.things_she_is_curious_about[-8:]

        questions = parsed.get("questions") or []
        if isinstance(questions, list):
            qs = QuestionService(self.db, user_id=self.user_id)
            for item in questions[:2]:
                if not isinstance(item, dict):
                    continue
                question = _clean(item.get("question"))
                if question and len(question) >= 10:
                    try:
                        importance = int(item.get("importance", 50))
                    except (TypeError, ValueError):
                        importance = 50
                    origin = _clean(item.get("origin")) or None
                    qs.upsert(
                        question,
                        source="self_authored",
                        importance=importance,
                        origin=origin,
                        conversation_id=conversation_id,
                    )

        memories = parsed.get("memories") or []
        if isinstance(memories, list):
            for m in memories[:3]:
                if not isinstance(m, dict):
                    continue
                content = _clean(m.get("content"))
                if not content or len(content) < 12:
                    continue
                mem_type = m.get("type", "fact")
                if mem_type not in _MEM_TYPES:
                    mem_type = "fact"
                valence = m.get("valence")
                if valence not in _VALENCES:
                    valence = None
                await self.memory.store(
                    content, type_=mem_type, valence=valence, conversation_id=conversation_id
                )

        rel.trust = _clamp(rel.trust + _num(parsed.get("trust_delta"), 0.0))
        rel.comfort = _clamp(rel.comfort + _num(parsed.get("comfort_delta"), 0.0))
        rel.humor = _clamp(rel.humor + _num(parsed.get("humor_delta"), 0.0))

        nicknames = parsed.get("nicknames") or []
        if isinstance(nicknames, list) and nicknames:
            for n in nicknames[:1]:
                n = _clean(n)
                if n and n not in rel.nicknames:
                    rel.nicknames.append(n[:64])

        topics = parsed.get("topics") or []
        if isinstance(topics, list):
            for t in topics:
                t = _clean(t)
                if t:
                    rel.topics_we_discuss[t[:128]] = rel.topics_we_discuss.get(t[:128], 0) + 1

        self.db.add(
            MoodRecord(
                user_id=self.user_id,
                mood=st.mood,
                energy=st.energy,
                source="digest",
                note=st.last_conversation_summary or None,
            )
        )
        # The porch is judged at the moment it ends by its own fast read, so
        # the slow per-turn digest never races it for the same impression.
        if conv is not None and conv.kind != "porch":
            upsert_impression(
                self.db,
                user_id=self.user_id,
                conversation_id=conversation_id,
                verdict=parsed.get("verdict"),
                moments_liked=parsed.get("moments_liked"),
                moments_not_liked=parsed.get("moments_not_liked"),
            )
        self.db.commit()

        if get_settings().console_emotions_enabled:
            logger.info(
                "mira.emotion | after digest mood=%s energy=%s",
                st.mood,
                st.energy,
            )


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(v: float) -> float:
    return min(1.0, max(0.0, v))


# Prevent background digest tasks from being garbage-collected mid-run. A
# bounded queue keeps the newest few turns digestible even during bursts: the
# model is slow on CPU, so digests run one at a time, but we no longer skip
# every turn that arrives while another is still cooking. The oldest waiting
# item is dropped when the queue is full so the freshest exchanges always land.
_DIGEST_QUEUE_MAX = 2
_DIGEST_QUEUE: "deque[tuple[AIProvider, int, int, str, str, list[dict[str, str]]]]" = deque()
_DIGEST_WORKER: asyncio.Task | None = None


def schedule_digest(
    provider: AIProvider,
    conversation_id: int,
    user_id: int,
    user_input: str,
    reply: str,
    history: list[dict[str, str]],
) -> None:
    """Reflect on a turn after a short beat (fire-and-forget, own DB session)."""
    if not get_settings().self_model_enabled:
        return
    if len(_DIGEST_QUEUE) >= _DIGEST_QUEUE_MAX:
        _DIGEST_QUEUE.popleft()
    _DIGEST_QUEUE.append((provider, conversation_id, user_id, user_input, reply, history))
    global _DIGEST_WORKER
    if _DIGEST_WORKER is None or _DIGEST_WORKER.done():
        _DIGEST_WORKER = asyncio.ensure_future(_digest_worker())


async def _digest_worker() -> None:
    while _DIGEST_QUEUE:
        provider, conversation_id, user_id, user_input, reply, history = _DIGEST_QUEUE.popleft()
        # Wait a beat before reflecting so a quick follow-up message is never
        # queued behind the digest (Ollama serializes requests per model).
        await asyncio.sleep(45)
        db = SessionLocal()
        try:
            svc = SelfModelService(db, provider, user_id=user_id)
            await svc.run_digest(conversation_id, user_input, reply, history)
        except Exception:
            logger.exception("self-digest failed")
        finally:
            db.close()
