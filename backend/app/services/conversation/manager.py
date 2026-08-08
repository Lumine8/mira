import json
import logging
import re
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Conversation, Message
from app.services.ai.base import AIProvider
from app.services.ai.prompt_builder import build_messages, clean_reply
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
    """Owns conversations: creation, persistence, and the generation loop."""

    def __init__(self, db: Session, provider: AIProvider) -> None:
        self.db = db
        self.provider = provider
        self.self_model = SelfModelService(db, provider)
        self._proposals: list = []
        self.last_reply = ""

    def start(self, *, kind: str = "text") -> Conversation:
        conv = Conversation(kind=kind)
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
                change = ToolService(self.db).propose_change(
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
                change = ToolService(self.db).propose_change(
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
                change = ToolService(self.db).propose_change(
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
                change = ToolService(self.db).propose_change(
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
                change = ToolService(self.db).propose_change(
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
                change = ToolService(self.db).propose_change(
                    "host_read", reason, {"path": path, "reason": reason}
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("read proposal failed (%s): %s", path, exc)

    def proposals(self) -> list:
        return list(self._proposals)

    async def generate_reply(
        self,
        conversation_id: int,
        user_input: str,
        *,
        source: str = "text",
        extra_context: str = "",
        image: str | None = None,
    ) -> AsyncIterator[str]:
        """Store the user message, stream a reply, store the assistant message.

        When ``image`` is a data URL the message is multimodal; Mira can see it.
        Browse intents written as [[browse|url|reason]] are turned into gated
        PendingChanges and surfaced via ``proposals()`` for an approval popup.
        """
        conversation = self.get(conversation_id)
        history = self.recent_messages(conversation_id)
        self.db.add(
            Message(conversation_id=conversation_id, speaker="user", content=user_input, image=image, source=source)
        )
        self.db.commit()

        self._proposals: list = []

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
        async for chunk in filt.clean(self.provider.stream_chat(messages)):
            chunks.append(chunk)
            yield chunk

        self._propose_browses_from(filt.raw(), conversation_id)
        self._propose_listens_from(filt.raw())
        self._propose_watches_from(filt.raw(), conversation_id)
        self._propose_selfedits_from(filt.raw())
        self._propose_runs_from(filt.raw())
        self._propose_reads_from(filt.raw())

        reply = clean_reply("".join(chunks))
        if not reply:
            raw = filt.raw()
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
                reply = "I asked " + "; ".join(bits) + ". It is yours to decide."
            elif "[[" in raw:
                logger.warning("reply suppressed but no proposal matched; raw=%.300s", raw)
                reply = "The request I tried to form didn't come through. Let me try again."
        self.last_reply = reply
        self.db.add(Message(conversation_id=conversation_id, speaker="mira", content=reply, source=source))
        self.db.commit()

        schedule_archive_write(get_settings().mira_archive_path)
        schedule_digest(self.provider, conversation_id, user_input, reply, history)
