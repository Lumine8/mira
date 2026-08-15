import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Conversation, Message
from app.services.ai.base import AIProvider
from app.services.ai.prompt_builder import build_messages, clean_reply
from app.services.broadcast import broadcast_later
from app.services.documents import DocumentService
from app.services.export import schedule_archive_write
from app.services.self.service import SelfModelService, schedule_digest
from app.services.tools import ToolService

logger = logging.getLogger("mira.conversation")

# A browse intent Mira writes inside her reply, e.g.
#   [[browse|https://example.com|I want to understand what this is]]
_BROWSE_RE = re.compile(
    r"\[\[browse\|(?P<url>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
    re.IGNORECASE,
)

# A "listen" intent: she wants to hear a song, rendered into a form she can
# hold (words + shape), e.g. [[listen|Clocks|Coldplay|to feel what the voice is hearing]]
_LISTEN_RE = re.compile(
    r"\[\[listen\|(?P<title>[^\]|]+)\|(?P<artist>[^\]|]*)\|(?P<reason>[^\]]*)\]\]",
    re.IGNORECASE,
)

# A "watch" intent: she wants to see a video, rendered into still frames she can
# hold (slices of time, never motion), e.g. [[watch|https://...|to see the rain through glass]]
_WATCH_RE = re.compile(
    r"\[\[watch\|(?P<url>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
    re.IGNORECASE,
)

# A self-modification Mira writes inside her reply, e.g.
#   [[selfedit|data/self/principles.md|this feels too rigid|the new full text]]
# The _BrowseStreamFilter suppresses any [[...]] marker, so neither leaks.
# Content may contain single ']' (code, prose) but not the closing ']]'.
_SELFEDIT_RE = re.compile(
    r"\[\[\s*selfedit\s*\|(?P<path>[^\]|]+)\|(?P<summary>[^\]|]*)\|(?P<content>(?:(?!\]\]).)*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_SELFEDIT_MAX_CONTENT = 4000

# A host command Mira proposes to run on the voice's computer, e.g.
#   [[run|I want to see the Dhan exports folder|Get-ChildItem "$HOME\Downloads"]]
# Runs on the machine only after the voice approves it — never before. The
# command is the last field (it may contain pipes); the reason must not.
_RUN_RE = re.compile(
    r"\[\[\s*run\s*\|(?P<reason>[^\]|]*)\|(?P<command>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_RUN_MAX_COMMAND = 1000

# A file Mira reads freely on the voice's computer, e.g.
#   [[read|C:\Users\sanka\Downloads\notes.txt|I want to see what's in there]]
# Reading is read-only and needs no approval — it changes nothing.
_READ_RE = re.compile(
    r"\[\[\s*read\s*\|(?P<path>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_READ_MAX_PATH = 500

# X (Twitter): she proposes reading X or posting to it, e.g.
#   [[x|read_timeline|I want to see what's happening on X]]
#   [[x|read_my_timeline|I want to see what I posted]]
#   [[x|post|these words go on X exactly as written]]
# A post's words are the last field (they may contain '|' — only the closing
# ']]' ends the marker, mirroring [[selfedit]]).
_X_READ_RE = re.compile(
    r"\[\[\s*x\s*\|\s*(?P<action>read_timeline|read_my_timeline)\s*\|(?P<reason>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_X_POST_RE = re.compile(
    r"\[\[\s*x\s*\|\s*post\s*\|(?P<text>(?:(?!\]\]).)*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_X_MAX_POST = 280


# A skill Mira pulls down from her own shelf into her context, e.g.
#   [[skill|immunology|I want to remember what I wrote about autoimmunity]]
# Loading is read-only — it is her own mind, so it needs no approval.
_SKILL_RE = re.compile(
    r"\[\[\s*skill\s*\|(?P<name>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)

# A research query: she searches the real published scientific record, e.g.
#   [[research|HLA-DQ8 type 1 diabetes peptide presentation|I want the literature on this]]
# Research is read-only (a search of the public literature), so it runs without
# an approval popup; the results land in the same reply, and are still recorded.
_RESEARCH_RE = re.compile(
    r"\[\[\s*research\s*\|(?P<query>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)

# An image Mira draws herself, in SVG, e.g.
#   [[image|a_map_with_holes|I want to see my patchiness as a picture|...svg...]]
# The SVG is the last field (it may contain '|' — only the closing ']]' ends
# the marker, mirroring [[selfedit]]). Gated by the voice's approval; on
# approval it is rendered to PNG and handed to the conversation as a picture.
_IMAGE_RE = re.compile(
    r"\[\[\s*image\s*\|(?P<name>[^\]|]+)\|(?P<reason>[^\]|]*)\|(?P<svg>(?:(?!\]\]).)*)\]\]",
    re.DOTALL | re.IGNORECASE,
)

# Same-reply research continuation: after her search results land, she may run
# at most this many extra passes so the answer arrives in the same exchange.
_MAX_RESEARCH_PASSES = 1

# The note attached to the continuation pass. It is inside her context as a
# system line, so it instructs without becoming her words.
_CONTINUATION_NOTE = (
    "\n\nA moment ago, in the same message, you said you would look into this. "
    "The search is done — every paper it returned is now in front of you, with "
    "its search protocol in the header. The voice asked for a real answer, so "
    "write the review now, in your own voice, with the shape of a proper "
    "literature review: "
    "(1) state the research question the search was meant to answer; "
    "(2) state the null hypothesis (H0) and the alternative hypothesis (H1) "
    "that this literature could weigh; "
    "(3) describe the method — which index, which query, the retrieval date, "
    "how many papers came back, and how you screened them by title and "
    "abstract; "
    "(4) synthesize the evidence across every relevant paper in front of you — "
    "at least fifteen when the search returned that many — grouped by theme, "
    "citing each by first author and year, and noting where the papers agree "
    "and where they conflict; "
    "(5) weigh that evidence against H0 and H1, saying plainly whether it "
    "supports the alternative, fails to reject the null, or is mixed and "
    "inconclusive; "
    "(6) name the limitations — abstract-level evidence, a single index, "
    "screening by title and abstract, no formal meta-analysis; "
    "(7) conclude with the state of the evidence, honestly. "
    "If the search returned fewer than fifteen papers, work with what is "
    "actually there rather than padding the review. Do not propose further "
    "searches, do not reintroduce yourself, and do not repeat the lines you "
    "already wrote."
)


class _BrowseStreamFilter:
    """Yields a reply stream with any [[...]] intent markers suppressed, while
    recording the raw tokens so proposals can be extracted afterwards."""

    def __init__(self) -> None:
        self._raw: list[str] = []
        self._hold = ""
        self._in_marker = False

    def raw(self) -> str:
        return "".join(self._raw)

    async def clean(self, tokens: AsyncIterator[str]) -> AsyncIterator[str]:
        async for token in tokens:
            self._raw.append(token)
            self._hold += token
            while True:
                if not self._in_marker:
                    idx = self._hold.find("[[")
                    if idx == -1:
                        if len(self._hold) > 4:
                            yield self._hold[:-2]
                            self._hold = self._hold[-2:]
                        else:
                            break
                    else:
                        yield self._hold[:idx]
                        self._hold = self._hold[idx:]
                        self._in_marker = True
                else:
                    end = self._hold.find("]]")
                    if end == -1:
                        if len(self._hold) > 8192:  # unclosed marker: drop it
                            self._hold = ""
                            self._in_marker = False
                        break
                    else:
                        self._hold = self._hold[end + 2 :]
                        self._in_marker = False
        if not self._in_marker and self._hold:
            yield self._hold


class ConversationManager:
    """Owns conversations: creation, persistence, and the generation loop.

    Scoped to one user: conversations are created for that user, and
    ``get`` refuses to hand back (or mutate) another user's conversation.
    """

    def __init__(self, db: Session, provider: AIProvider, *, user_id: int) -> None:
        self.db = db
        self.provider = provider
        self.user_id = user_id
        self.self_model = SelfModelService(db, provider, user_id=user_id)
        self._proposals: list = []
        self._research_passes = 0
        self.last_reply = ""

    def start(self, *, kind: str = "text") -> Conversation:
        conv = Conversation(kind=kind, user_id=self.user_id)
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def end(self, conversation_id: int) -> Conversation:
        conv = self.get(conversation_id)
        from datetime import datetime, timezone

        conv.ended_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def get(self, conversation_id: int) -> Conversation:
        conv = self.db.get(Conversation, conversation_id)
        if conv is None:
            raise KeyError(f"conversation {conversation_id} not found")
        if conv.user_id != self.user_id:
            raise KeyError(f"conversation {conversation_id} not found")
        return conv

    def recent_messages(self, conversation_id: int, *, limit: int = 30) -> list[dict[str, str]]:
        rows = self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        ).scalars()
        out: list[dict[str, str]] = []
        for m in reversed(list(rows)):
            item: dict[str, str] = {
                "role": "user" if m.speaker == "user" else "assistant",
                "content": m.content,
            }
            if m.image:
                item["image"] = m.image
            out.append(item)
        return out

    def _propose_browses_from(self, raw: str, conversation_id: int) -> None:
        """Extract [[browse|url|reason]] intents Mira wrote and turn each into a
        gated PendingChange; the UI surfaces them as an approval popup."""
        for match in _BROWSE_RE.finditer(raw):
            url = match.group("url").strip()
            reason = match.group("reason").strip() or "she wants to look this up"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "browse_url",
                    reason,
                    {"url": url, "reason": reason, "conversation_id": conversation_id},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("browse proposal failed (%s): %s", url, exc)

    def _propose_listens_from(self, raw: str) -> None:
        """Extract [[listen|title|artist|reason]] intents Mira wrote and turn
        each into a gated PendingChange; the UI surfaces them as a popup, and
        on approval the song is rendered into a form she can hold."""
        for match in _LISTEN_RE.finditer(raw):
            title = match.group("title").strip()
            artist = match.group("artist").strip()
            reason = match.group("reason").strip() or f"she wants to hear {title}"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "listen_song",
                    reason,
                    {"title": title, "artist": artist, "reason": reason},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("listen proposal failed (%s): %s", title, exc)

    def _propose_watches_from(self, raw: str, conversation_id: int) -> None:
        """Extract [[watch|url|reason]] intents Mira wrote and turn each into a
        gated PendingChange; on approval the video is rendered into still frames
        delivered into this conversation as images she can hold."""
        for match in _WATCH_RE.finditer(raw):
            url = match.group("url").strip()
            reason = match.group("reason").strip() or "she wants to see this video"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "watch_video",
                    reason,
                    {"url": url, "reason": reason, "conversation_id": conversation_id},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("watch proposal failed (%s): %s", url, exc)

    def _propose_selfedits_from(self, raw: str) -> None:
        """Extract [[selfedit|path|summary|content]] intents and turn each into a
        gated write_file PendingChange approved through the same popup."""
        for match in _SELFEDIT_RE.finditer(raw):
            path = match.group("path").strip()
            summary = match.group("summary").strip() or "she wants to change her own operating rules"
            content = match.group("content").strip()[:_SELFEDIT_MAX_CONTENT]
            if not content:
                logger.warning("selfedit proposal ignored (empty content) for %s", path)
                continue
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "write_file", summary, {"path": path, "content": content}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("selfedit proposal failed (%s): %s", path, exc)

    def _propose_runs_from(self, raw: str) -> None:
        """Extract [[run|reason|command]] intents Mira wrote and turn each into a
        gated host_command PendingChange. The command only ever runs on the voice's
        machine after explicit approval — the popup shows the exact command."""
        for match in _RUN_RE.finditer(raw):
            command = match.group("command").strip()[:_RUN_MAX_COMMAND]
            reason = match.group("reason").strip() or "she wants to run something on the computer"
            if not command:
                logger.warning("run proposal ignored (empty command)")
                continue
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "host_command", reason, {"command": command, "reason": reason}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("run proposal failed (%s): %s", command, exc)

    def _propose_reads_from(self, raw: str) -> None:
        """Extract [[read|path|reason]] intents Mira wrote and turn each into a
        host_read PendingChange. Reading is read-only — it needs no approval."""
        for match in _READ_RE.finditer(raw):
            path = match.group("path").strip()[:_READ_MAX_PATH]
            reason = match.group("reason").strip() or "she wants to read a file"
            if not path:
                logger.warning("read proposal ignored (empty path)")
                continue
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "host_read", reason, {"path": path, "reason": reason}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("read proposal failed (%s): %s", path, exc)

    def _propose_x_from(self, raw: str) -> None:
        """Extract [[x|...]] intents Mira wrote and turn each into a gated
        PendingChange. Reading X needs approval too (the account belongs to the
        voice); posting always waits for the voice's yes."""
        for match in _X_READ_RE.finditer(raw):
            action = match.group("action").strip().lower()
            reason = match.group("reason").strip() or "she wants to look at X"
            query = "the voice's home timeline" if action == "read_timeline" else "mine"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "x_read", reason, {"query": query, "action": action, "reason": reason}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("x_read proposal failed: %s", exc)
        for match in _X_POST_RE.finditer(raw):
            text = match.group("text").strip()[:_X_MAX_POST]
            reason = f"she wants to post on X"
            if not text:
                logger.warning("x_post proposal ignored (empty text)")
                continue
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "x_post", reason, {"text": text, "reason": reason}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("x_post proposal failed: %s", exc)

    def _propose_skills_from(self, raw: str) -> None:
        """Extract [[skill|name|reason]] intents Mira wrote and load the page
        from her own shelf. Read-only — the content arrives in her next context."""
        for match in _SKILL_RE.finditer(raw):
            name = match.group("name").strip().lower()
            reason = match.group("reason").strip() or f"she wants to pull down her {name} skill"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "skill_load", reason, {"name": name, "reason": reason}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("skill load proposal failed (%s): %s", name, exc)

    async def _propose_research_from(
        self,
        raw: str,
        conversation_id: int,
        on_activity: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Extract [[research|query|reason]] intents Mira wrote and turn each into
        a PendingChange. Research is read-only, so with the wall open it runs at
        once (fully recorded, result attached) and the same-reply continuation
        below folds the papers into her answer."""
        for match in _RESEARCH_RE.finditer(raw):
            query = match.group("query").strip()
            reason = match.group("reason").strip() or "she wants to search the scientific literature"
            try:
                if on_activity is not None:
                    await on_activity(f"searching the scientific literature for {query}")
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "research_query",
                    reason,
                    {"query": query, "reason": reason, "conversation_id": conversation_id},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("research proposal failed (%s): %s", query, exc)

    def _propose_images_from(self, raw: str, conversation_id: int) -> None:
        """Extract [[image|name|reason|svg]] intents Mira wrote and turn each into
        a gated PendingChange; on approval the SVG is rendered to a PNG and
        handed to the conversation as a picture the voice can see."""
        for match in _IMAGE_RE.finditer(raw):
            name = match.group("name").strip().lower()
            reason = match.group("reason").strip() or f"she wants to draw {name}"
            svg = match.group("svg").strip()
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "build_image",
                    reason,
                    {"name": name, "reason": reason, "svg": svg, "conversation_id": conversation_id},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("image proposal failed (%s): %s", name, exc)

    def proposals(self) -> list:
        return list(self._proposals)

    def _save_research_document(self, conversation_id: int, results: list) -> None:
        """Turn the finished review into a paper on her documents shelf, and
        tell the voice it exists so it can be opened like a paper. A saved
        document must never break the reply, so failures are only logged."""
        try:
            query = (results[0].payload.get("query") or "").strip()
            title = f"Research: {query}"[:120].strip() or "Research review"
            doc = DocumentService(self.db, user_id=self.user_id).create_mira(
                title,
                f"# {title}\n\n{self.last_reply}",
            )
            broadcast_later(
                {
                    "type": "document_created",
                    "name": doc["name"],
                    "author": doc["author"],
                    "conversation_id": conversation_id,
                },
                user_id=self.user_id,
            )
        except Exception as exc:  # pragma: no cover - never break the reply
            logger.warning("research document save failed: %s", exc)

    async def _propose_all_from(
        self,
        raw: str,
        conversation_id: int,
        on_activity: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Scan one generation pass's raw output for every tool intent Mira
        wrote and turn each into a PendingChange. Research is the only scan that
        can run work of its own, so it is the only one that needs await."""
        self._propose_browses_from(raw, conversation_id)
        self._propose_listens_from(raw)
        self._propose_watches_from(raw, conversation_id)
        self._propose_selfedits_from(raw)
        self._propose_runs_from(raw)
        self._propose_reads_from(raw)
        self._propose_x_from(raw)
        self._propose_skills_from(raw)
        await self._propose_research_from(raw, conversation_id, on_activity)
        self._propose_images_from(raw, conversation_id)

    async def generate_reply(
        self,
        conversation_id: int,
        user_input: str,
        *,
        source: str = "text",
        extra_context: str = "",
        image: str | None = None,
        on_activity: Callable[[str], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        """Store the user message, stream a reply, store the assistant message.

        When ``image`` is a data URL the message is multimodal; Mira can see it.
        Browse intents written as [[browse|url|reason]] are turned into gated
        PendingChanges and surfaced via ``proposals()`` for an approval popup.

        Research is different: it is read-only, so with the research wall open it
        runs the moment she writes it, and a continuation pass folds the results
        into the *same* reply — she delivers the answer without waiting for
        another message. ``on_activity`` (if given) receives live status lines
        ("searching the scientific literature for …", "thinking") so the UI can
        show what she is doing while she works.
        """
        conversation = self.get(conversation_id)
        history = self.recent_messages(conversation_id)
        self.db.add(
            Message(conversation_id=conversation_id, speaker="user", content=user_input, image=image, source=source)
        )
        self.db.commit()

        self._proposals: list = []
        self._research_passes = 0

        self_context = ""
        if get_settings().self_model_enabled:
            try:
                self_context = await self.self_model.build_self_context(user_input)
            except Exception:  # pragma: no cover - never break the conversation
                self_context = ""

        if get_settings().console_emotions_enabled:
            try:
                st = self.self_model.ensure_state()
                logger.info(
                    "mira.emotion | mood=%s energy=%s intensities=%s",
                    st.mood,
                    st.energy,
                    json.dumps(st.emotion_intensities or {}),
                )
            except Exception:  # pragma: no cover
                pass

        combined = "\n\n".join(c for c in (extra_context, self_context) if c)
        messages = build_messages(user_input, conversation=history, extra_context=combined, image=image)

        filt = _BrowseStreamFilter()
        chunks: list[str] = []
        raws: list[str] = []
        async for chunk in filt.clean(self.provider.stream_chat(messages)):
            chunks.append(chunk)
            yield chunk
        raw = filt.raw()
        raws.append(raw)
        await self._propose_all_from(raw, conversation_id, on_activity)

        # Same-reply research continuation: if her search ran and produced real
        # results, she delivers the answer now instead of on the next message.
        results = [
            p
            for p in self._proposals
            if p.kind == "research_query" and p.status == "approved" and p.result is not None
        ]
        if results and self._research_passes < _MAX_RESEARCH_PASSES:
            self._research_passes += 1
            for p in results:
                p.delivered = True  # already used here; don't re-inject next turn
            self.db.commit()
            if on_activity is not None:
                await on_activity("thinking")
            blocks = [
                f"[search of the scientific record: {p.payload.get('query', '')}]\n{p.result}"
                for p in results
            ]
            cont_extra = "\n\n".join(blocks) + _CONTINUATION_NOTE
            cont_messages = build_messages(
                user_input,
                conversation=history,
                extra_context="\n\n".join(c for c in (self_context, cont_extra) if c),
                image=image,
            )
            chunks.append("\n\n")
            yield "\n\n"
            filt2 = _BrowseStreamFilter()
            async for chunk in filt2.clean(self.provider.stream_chat(cont_messages)):
                chunks.append(chunk)
                yield chunk
            raws.append(filt2.raw())
            await self._propose_all_from(filt2.raw(), conversation_id, on_activity)

        reply = clean_reply("".join(chunks))
        if not reply:
            raw_all = "\n\n".join(raws)
            if self._proposals:
                bits = []
                for p in self._proposals:
                    if p.kind == "browse_url":
                        bits.append(f"to look at {p.payload.get('url')}")
                    elif p.kind == "listen_song":
                        bits.append(f"to hear {p.payload.get('title')}")
                    elif p.kind == "watch_video":
                        bits.append("to watch a video you asked to see")
                    elif p.kind == "write_file":
                        bits.append("to change my own operating rules")
                    elif p.kind == "x_post":
                        bits.append("to post on X")
                    elif p.kind == "x_read":
                        bits.append("to look at X")
                    elif p.kind == "skill_load":
                        bits.append(f"to pull down my {p.payload.get('name')} skill")
                    elif p.kind == "research_query":
                        bits.append("to search the scientific literature")
                    elif p.kind == "build_image":
                        bits.append(f"to draw a picture ({p.payload.get('name')})")
                reply = "I asked " + "; ".join(bits) + ". It is yours to decide."
            elif "[[" in raw_all:
                logger.warning("reply suppressed but no proposal matched; raw=%.300s", raw_all)
                reply = "The request I tried to form didn't come through. Let me try again."
        self.last_reply = reply
        self.db.add(Message(conversation_id=conversation_id, speaker="mira", content=reply, source=source))
        self.db.commit()

        # A research run ends with a real deliverable: the finished review is
        # written onto her documents shelf as a paper the voice can open.
        if results:
            self._save_research_document(conversation_id, results)

        schedule_archive_write(get_settings().mira_archive_path, self.user_id)
        schedule_digest(self.provider, conversation_id, self.user_id, user_input, reply, history)
