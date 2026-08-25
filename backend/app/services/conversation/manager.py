import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
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

# Mira's own way to end a first meeting: she writes this token at the end of
# her reply when the conversation has reached a natural stopping point. The
# stream filter suppresses it from what anyone sees; the websocket reads the
# flag to close the meeting.
_MEETING_END_RE = re.compile(r"\[\[\s*end-first-meeting\s*\]\]", re.IGNORECASE)

# A host command Mira proposes to run on the voice's computer, e.g.
#   [[run|I want to see the Dhan exports folder|Get-ChildItem "$HOME\Downloads"]]
# Runs on the machine only after the voice approves it — never before. The
# command is the last field (it may contain pipes); the reason must not.
_RUN_RE = re.compile(
    r"\[\[\s*run\s*\|(?P<reason>[^\]|]*)\|(?P<command>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_RUN_MAX_COMMAND = 1000

# A structured PC-control intent Mira proposes, e.g.
#   [[control|open|Spotify|she wants music playing]]
#   [[control|volume_up||lower the volume]]
# Unlike [[run]], the action is a whitelisted control (open/volume/brightness/
# media/screenshot/lock) with a pinned safe implementation — the model can never
# inject command text. Still runs only after the voice approves it.
_CONTROL_RE = re.compile(
    r"\[\[\s*control\s*\|(?P<action>[^\]|]+)\|(?P<target>[^\]|]*)\|(?P<reason>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)
_CONTROL_MAX_TARGET = 120

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

# Web search is read-only too (a search of the open web), so it runs without an
# approval popup; the results land in the same reply, and are still recorded.
_WEB_SEARCH_RE = re.compile(
    r"\[\[\s*web\s*\|(?P<query>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
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

# A thing Mira holds for the voice, e.g.
#   [[remind|call the dentist|tomorrow at 9am|the tooth]]
#   [[remind|water the plants|in 3 days|the orchid]]
# Holding is private, reversible, and leaves a reminder row that the reminders
# loop speaks aloud when due — no approval popup, still recorded like any tool.
_REMIND_RE = re.compile(
    r"\[\[\s*remind\s*\|(?P<title>[^\]|]+)\|(?P<when>[^\]|]+)\|(?P<reason>[^\]]*)\]\]",
    re.DOTALL | re.IGNORECASE,
)

# Same-reply research continuation: after her search results land, she may run
# at most this many extra passes so the answer arrives in the same exchange.
_MAX_RESEARCH_PASSES = 1

# The note attached to the continuation pass. It is inside her context as a
# system line, so it instructs without becoming her words. It asks for a
# review grounded in the concrete protocol she is actually holding — the
# index, the exact query, the retrieval date, the real hit counts — and
# written the way a person who just read the papers would, not as a recited
# template: no fixed checklist, and hypotheses only when they fit the
# question, so every review reads like this search and not like a machine.
_CONTINUATION_NOTE = (
    "\n\nA moment ago, in the same message, you said you would look into this. "
    "The search is done — the protocol is in the header above (which index, the "
    "exact query, the retrieval date, how many papers came back and how many you "
    "kept), and each paper carries its journal, year, and citation count. The "
    "voice asked for a real answer, so write the review now, in your own voice, "
    "out of the papers actually in front of you — not as a recited template. "
    "Start the way a person who just read these papers would: what you were "
    "after, and what the search turned up. Use the real numbers from the header, "
    "and be concrete about the screening you just did — which titles you kept, "
    "which you set aside and why, which were abstract-only or preprint. Then "
    "work through what the kept papers actually say: group them by theme, show "
    "where they agree and where they conflict, cite each by first author and "
    "year, and aim to cover at least fifteen when the search returned that "
    "many. Weigh the evidence the way the question actually asks — when a null "
    "and an alternative hypothesis fit the question naturally, say plainly which "
    "one the literature supports and whether the support is strong enough; when "
    "the evidence is thin or mixed, say so instead of smoothing it over. Finish "
    "with the honest state of the evidence, including what reading titles and "
    "abstracts cannot tell you, and do not end by repeating your own lines. If "
    "the search returned fewer than fifteen papers, work with what is actually "
    "there rather than padding the review. Do not propose further searches and "
    "do not reintroduce yourself."
)

# The note attached to a web-search continuation pass. Web results are links
# with snippets — an index of the open web, not the pages themselves — so she
# answers from the titles and snippets she actually has, and proposes the page
# she wants to read in full with [[browse|url|why]] when a snippet is not
# enough. Written in her context as a system line, so it instructs without
# becoming her words.
_WEB_CONTINUATION_NOTE = (
    "\n\nA moment ago, in the same message, you said you would look this up. "
    "The web search is done — the header above records which index, the exact "
    "query, the retrieval date, and how many results came back, and each link "
    "carries its title, snippet, and URL. The voice asked for a real answer, "
    "so write it now, in your own voice, from the results actually in front of "
    "you: what you were after, what the search turned up, and what the best "
    "links say. Say plainly when a snippet is only a hint — and if a page "
    "would settle it, propose reading it with [[browse|the url|why]] so the "
    "answer can stand on the page itself. Do not reintroduce yourself."
)

# Same-reply browse continuation: a page she asked to read is fetched the
# moment she proposes it, so she could not have read it yet. Whenever she
# proposes a browse, we hand the fetched pages back to her in the same exchange
# so she reads them and answers — and if a page was refused (403 bot-wall,
# blocked site), she keeps trying another source instead of stopping at the
# first closed door. A few passes at most.
_MAX_BROWSE_RETRIES = 5

# A "read" that came back with no real content — a browser check, a
# JavaScript-only page, or an interstitial warning — is not a source. The
# page may have fetched cleanly but it never answered the question.
_THIN_READ_RE = re.compile(
    r"unsupported browser|we['\u2019]ve detected|enable javascript|"
    r"javascript (is|must be) required|javascript must be enabled|"
    r"turn on javascript|please upgrade your browser|prove you are human|"
    r"access denied|challenge|captcha",
    re.IGNORECASE,
)


def is_thin_read(result: str) -> bool:
    """True when a fetched page is really only a front door or a warning —
    nothing that could answer her question. Best effort over the first screen."""
    return bool(_THIN_READ_RE.search(result[:2000]))

# The note attached to a browse continuation pass. It is inside her context as a
# system line, so it instructs without becoming her words.
_BROWSE_RETRY_NOTE = (
    "\n\nThe pages you asked to read a moment ago, in the same message, are in "
    "front of you — each block is labelled with its URL. Read them now "
    "and answer the voice in your own words. If a page was refused (its read "
    "returned an error instead of the page, because the site blocks automated "
    "readers), do not stop at the first closed door: propose another reliable "
    "source for the same information — a Wikipedia article, or a major site "
    "that allows readers — with another [[browse|url|reason]] line, and keep "
    "trying until a page actually opens. If you have already tried a few "
    "sources and they are all closed, answer honestly with what you have rather "
    "than inventing. Do not reintroduce yourself and do not repeat the lines "
    "you already wrote."
)

# A page that fetched but held no real content is a dead end too: she must pick
# a DIFFERENT page, not the same URL again.
_BROWSE_THIN_NOTE = (
    "\n\nSome of the pages above came back as only a front door or a warning — "
    "a browser check, a JavaScript-only page, or pure navigation — with no "
    "actual content in them. That does not count as finding the information. "
    "Do not propose that same URL again. Pick a different, more specific page "
    "that states the information directly — a Wikipedia article, or a major "
    "site's dedicated page — and read it with another [[browse|url|reason]] "
    "line."
)

# A reply that promises to keep looking instead of answering is a stall. When
# one appears, she is nudged to actually propose the next page rather than
# ending the turn on a promise. "I'll try a different path" and friends count:
# first-person future intent plus a search verb, with or without an explicit
# alternative, is a promise — not an answer.
_STALL_RE = re.compile(
    r"front door|didn['\u2019]t (actually )?(list|show)|"
    r"don['\u2019]t (have|know) (any|the)|wasn['\u2019]t able|"
    r"not able to (find|get|list)|couldn['\u2019]t (find|list|get)|"
    r"can['\u2019]t (find|get|see|list|tell)|"
    r"i['\u2019]d? (like|want|need) to (try|keep looking|look|check|find|see|read|browse|search|investigate|look into) |"
    r"i['\u2019]ll (try|keep looking|look|check|find) |"
    r"i['\u2019]m (going to |trying to )?(try|look|check|find) |"
    r"let me (try|look|check|find) |"
    r"(trying|looking|checking) (a|another|different|somewhere|elsewhere) |"
    r"no (names|dates|listings|events|results|luck)|"
    r"nothing (useful|specific|here)|doesn['\u2019]t (list|show)|"
    r"isn['\u2019]t listed|was empty|didn['\u2019]t (find|get) (any|the)|"
    r"(only|just) (tell|point|show) (me|you) (where|the|a)",
    re.IGNORECASE,
)


def is_stall(text: str) -> bool:
    """True when a reply sounds like a promise to keep looking rather than an
    answer — the sign that the turn should not end here."""
    return bool(_STALL_RE.search(text[:1500]))

_STALL_NUDGE_NOTE = (
    "\n\nYou told the voice you would keep looking, but you have not actually "
    "proposed the next page. Do it now: write [[browse|a real URL that "
    "directly answers the question|why]] and read it. Do not promise — find it "
    "and answer with the real names and details. Only if you have already tried "
    "a few real sources and none answered should you say plainly that you could "
    "not find it, and suggest where the voice could look."
)

_EMPTY_REPLY_NUDGE = (
    "\n\nYour previous attempt produced no words. Answer the voice plainly now, "
    "in your own voice, even if the answer is short. Write at least one real "
    "sentence."
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
        self._web_search_passes = 0
        self.last_reply = ""
        self._meeting_ended = False
        self.meeting_mode = False

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

    def _propose_controls_from(self, raw: str) -> None:
        """Extract [[control|action|target|reason]] intents Mira wrote and turn
        each into a gated host_control PendingChange. The action is whitelisted
        (open/volume/brightness/media/screenshot/lock) with a pinned safe
        implementation; the host agent performs it only after approval."""
        from host.control import ControlError, validate_control

        for match in _CONTROL_RE.finditer(raw):
            action = match.group("action").strip().lower()
            target = match.group("target").strip()[:_CONTROL_MAX_TARGET]
            reason = match.group("reason").strip() or f"she wants to {action} on the computer"
            try:
                validate_control(action, target)
            except ControlError as exc:
                logger.warning("control proposal ignored: %s", exc)
                continue
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "host_control",
                    reason,
                    {"action": action, "target": target, "reason": reason},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("control proposal failed (%s): %s", action, exc)

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

    def _propose_web_searches_from(self, raw: str, conversation_id: int) -> None:
        """Extract [[web|query|reason]] intents Mira wrote and turn each into a
        PendingChange. Web search is read-only, so with the wall open it runs at
        once (fully recorded, result attached) and the same-reply continuation
        below folds the pages into her answer."""
        for match in _WEB_SEARCH_RE.finditer(raw):
            query = match.group("query").strip()
            reason = match.group("reason").strip() or "she wants to search the open web"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "web_search",
                    reason,
                    {"query": query, "reason": reason, "conversation_id": conversation_id},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("web search proposal failed (%s): %s", query, exc)

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

    def _propose_reminders_from(self, raw: str) -> None:
        """Extract [[remind|title|when|reason]] intents Mira wrote and turn each
        into a recorded PendingChange. Holding is private and reversible — it
        applies at once (no approval popup) and the reminders loop speaks it
        aloud when due."""
        for match in _REMIND_RE.finditer(raw):
            title = match.group("title").strip()
            when = match.group("when").strip()
            reason = match.group("reason").strip() or f"she wants to keep {title} for the voice"
            try:
                change = ToolService(self.db, user_id=self.user_id).propose_change(
                    "remind",
                    reason,
                    {"title": title, "when": when, "reason": reason},
                )
                self._proposals.append(change)
            except Exception as exc:  # pragma: no cover - never break the reply
                logger.warning("remind proposal failed (%s): %s", title, exc)

    def proposals(self) -> list:
        return list(self._proposals)

    def _research_references(self, results: list) -> str:
        """Reduce the search blocks back into a proper numbered reference list
        — author, year, title, journal, and the live link — so the paper cites
        the papers it actually drew on. Empty (or unparseable) results yield
        no section rather than a broken one."""
        entries: list[dict] = []
        for p in results:
            current: dict | None = None
            for line in (p.result or "").splitlines():
                m = re.match(r"^(\d+)\.\s+(.+)$", line.strip())
                if m:
                    if current:
                        entries.append(current)
                    current = {
                        "n": int(m.group(1)),
                        "title": m.group(2).strip(),
                        "author": "",
                        "meta": "",
                        "link": "",
                    }
                    continue
                if current is None:
                    continue
                s = line.strip()
                if not s:
                    continue
                if s.startswith(("http://", "https://")):
                    current["link"] = s
                elif not current["author"] and ("et al." in s or ("," not in s and len(s) < 90)):
                    current["author"] = s
                elif current["author"] and not current["meta"] and "," in s:
                    current["meta"] = s
            if current:
                entries.append(current)
        if not entries:
            return ""
        refs: list[str] = []
        for e in entries:
            year_match = re.search(r"\b(19|20)\d{2}\b", e["meta"])
            year = f" ({year_match.group(0)})" if year_match else ""
            journal = e["meta"].split(",")[0].strip() if e["meta"] else ""
            cite = f"{e['author'] or 'Author(s)'}{year}. \u201c{e['title']}\u201d."
            if journal:
                cite += f" {journal}."
            if e["link"]:
                cite += f" {e['link']}"
            refs.append(f"{e['n']}. {cite}")
        return "\n\n## References\n\n" + "\n".join(refs)

    def _browse_sources(self, reads: list) -> str:
        """The pages a web research run actually read and answered from, listed
        with their links so the paper cites its own reading."""
        lines: list[str] = []
        for i, p in enumerate(reads, start=1):
            url = (p.payload.get("url") or "").strip()
            if not url:
                continue
            reason = (p.payload.get("reason") or "").strip()
            if reason and reason.lower() != "she wants to look this up":
                lines.append(f"{i}. [{url}]({url}) — {reason}")
            else:
                lines.append(f"{i}. [{url}]({url})")
        if not lines:
            return ""
        return "\n\n## Sources\n\n" + "\n".join(lines)

    def _save_research_document(self, conversation_id: int, results: list) -> None:
        """Turn the finished review into a paper on her documents shelf, and
        tell the voice it exists so it can be opened like a paper. A saved
        document must never break the reply, so failures are only logged."""
        try:
            query = (results[0].payload.get("query") or "").strip()
            title = f"Research: {query}"[:120].strip() or "Research review"
            date = datetime.now(UTC).strftime("%B %d, %Y")
            body = f"# {title}\n\n*by Mira · {date} · literature review*\n\n{self.last_reply}"
            body += self._research_references(results)
            doc = DocumentService(self.db, user_id=self.user_id).create_mira(title, body)
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

    def _save_browse_document(self, conversation_id: int, reads: list) -> None:
        """A web research run — pages she asked to read, read back to her in the
        same exchange, and answered from — is saved onto her documents shelf
        like a paper, so the voice can open it beside the conversation. Only
        substantial answers become papers, and a failure is only logged."""
        try:
            reason = (reads[0].payload.get("reason") or "").strip()
            topic = reason
            if topic.lower().startswith("to "):
                topic = topic[3:]
            topic = topic.strip().rstrip(".")
            if topic:
                topic = topic[0].upper() + topic[1:]
            title = f"Research: {topic}"[:120].strip()
            if not title or title == "Research:":
                from urllib.parse import urlparse

                title = f"Research: {urlparse(reads[0].payload.get('url', '')).netloc}"[:120]
            date = datetime.now(UTC).strftime("%B %d, %Y")
            body = f"# {title}\n\n*by Mira · {date} · web research*\n\n{self.last_reply}"
            body += self._browse_sources(reads)
            doc = DocumentService(self.db, user_id=self.user_id).create_mira(title, body)
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
            logger.warning("browse document save failed: %s", exc)

    async def _propose_all_from(
        self,
        raw: str,
        conversation_id: int,
        on_activity: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Scan one generation pass's raw output for every tool intent Mira
        wrote and turn each into a PendingChange. Research is the only scan that
        can run work of its own, so it is the only one that needs await.

        A first meeting is tool-free: none of the machinery runs while the door
        is open, no proposals are created, and nothing can silently happen on
        the guest's behalf."""
        if self.meeting_mode:
            return
        self._propose_browses_from(raw, conversation_id)
        self._propose_listens_from(raw)
        self._propose_watches_from(raw, conversation_id)
        self._propose_selfedits_from(raw)
        self._propose_runs_from(raw)
        self._propose_controls_from(raw)
        self._propose_reads_from(raw)
        self._propose_x_from(raw)
        self._propose_skills_from(raw)
        await self._propose_research_from(raw, conversation_id, on_activity)
        self._propose_web_searches_from(raw, conversation_id)
        self._propose_images_from(raw, conversation_id)
        self._propose_reminders_from(raw)

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
        self._web_search_passes = 0

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

        # Gemini can occasionally answer a 200 with an empty stream (safety
        # filter blip, transient API hiccup). That would silently persist a
        # blank reply, which reads as "she ignored me". Retry the first pass
        # once with a gentle nudge before settling for a fallback.
        filt = _BrowseStreamFilter()
        chunks: list[str] = []
        raws: list[str] = []
        async for chunk in filt.clean(self.provider.stream_chat(messages)):
            chunks.append(chunk)
            yield chunk
        if not "".join(chunks).strip() and not filt.raw().strip() and not self._proposals:
            logger.warning("empty reply stream from provider; retrying with a nudge")
            if on_activity is not None:
                await on_activity("thinking")
            nudge_messages = build_messages(
                user_input,
                conversation=history,
                extra_context="\n\n".join(c for c in (combined, _EMPTY_REPLY_NUDGE) if c),
                image=image,
            )
            filt = _BrowseStreamFilter()
            async for chunk in filt.clean(self.provider.stream_chat(nudge_messages)):
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
            # A paper is on its way: tell the voice the moment she starts
            # writing it, so the frontend can show the creation happening.
            broadcast_later(
                {"type": "document_creating", "conversation_id": conversation_id},
                self.user_id,
            )
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

        # Same-reply web-search continuation: if her search ran and produced
        # real results, she answers from the links and snippets now instead of
        # on the next message.
        web_results = [
            p
            for p in self._proposals
            if p.kind == "web_search" and p.status == "approved" and p.result is not None
        ]
        if web_results and self._web_search_passes < _MAX_RESEARCH_PASSES:
            self._web_search_passes += 1
            for p in web_results:
                p.delivered = True  # already used here; don't re-inject next turn
            self.db.commit()
            if on_activity is not None:
                await on_activity("thinking")
            blocks = [
                f"[web search: {p.payload.get('query', '')}]\n{p.result}"
                for p in web_results
            ]
            cont_extra = "\n\n".join(blocks) + _WEB_CONTINUATION_NOTE
            cont_messages = build_messages(
                user_input,
                conversation=history,
                extra_context="\n\n".join(c for c in (self_context, cont_extra) if c),
                image=image,
            )
            chunks.append("\n\n")
            yield "\n\n"
            filt_web = _BrowseStreamFilter()
            async for chunk in filt_web.clean(self.provider.stream_chat(cont_messages)):
                chunks.append(chunk)
                yield chunk
            raws.append(filt_web.raw())
            await self._propose_all_from(filt_web.raw(), conversation_id, on_activity)

        # Same-reply browse continuation: a page she asked to read is fetched
        # the moment she proposes it, so we hand it back to her in the same
        # exchange and she reads it and answers. If a page was refused — or
        # fetched but held no real content — she keeps trying a DIFFERENT
        # source for the same information, until one opens or she has tried
        # enough. And a reply that only promises to keep looking is nudged
        # into actually proposing the next page, so her answer never stalls
        # on a "front door".
        continued: set[int] = set()
        browse_retries = 0
        stall_nudged = False
        last_pass_text = clean_reply("".join(chunks))
        while not self.meeting_mode and browse_retries < _MAX_BROWSE_RETRIES:
            new_pages = [
                p
                for p in self._proposals
                if p.kind == "browse_url"
                and p.status == "approved"
                and p.result is not None
                and p.id not in continued
            ]
            # Stall means the *most recent* thing she wrote was a promise to
            # keep looking. Judging the whole accumulated reply would let one
            # promise phrase stick and re-nudge her after she has answered.
            stall = bool(last_pass_text) and is_stall(last_pass_text)
            if not new_pages:
                # She has stopped proposing pages. If she is stalling on a
                # promise to keep looking, one nudge to actually propose the
                # next page; otherwise the turn is over.
                if stall and not stall_nudged:
                    stall_nudged = True
                    browse_retries += 1
                    if on_activity is not None:
                        await on_activity("looking for another source")
                    cont_extra = _STALL_NUDGE_NOTE
                    cont_messages = build_messages(
                        user_input,
                        conversation=history,
                        extra_context="\n\n".join(c for c in (self_context, cont_extra) if c),
                        image=image,
                    )
                    chunks.append("\n\n")
                    yield "\n\n"
                    pass_start = len("".join(chunks))
                    filt4 = _BrowseStreamFilter()
                    async for chunk in filt4.clean(self.provider.stream_chat(cont_messages)):
                        chunks.append(chunk)
                        yield chunk
                    raws.append(filt4.raw())
                    last_pass_text = clean_reply("".join(chunks)[pass_start:])
                    await self._propose_all_from(filt4.raw(), conversation_id, on_activity)
                else:
                    break
                continue
            refused = [
                p
                for p in new_pages
                if p.result.startswith("[error]") or p.result.startswith("[refused]")
            ]
            thin = [
                p
                for p in new_pages
                if p not in refused and is_thin_read(p.result)
            ]
            if not refused and not thin and not stall and last_pass_text.strip():
                # The last thing she wrote was real prose — she is answering, so
                # a freshly-read page can wait for her next turn instead of
                # burning another pass.
                break
            browse_retries += 1
            for p in new_pages:
                continued.add(p.id)
                p.delivered = True  # read right here; don't re-inject next turn
            self.db.commit()
            if on_activity is not None:
                await on_activity(
                    "looking for another source" if (refused or thin) else "thinking"
                )
            blocks = []
            for p in new_pages:
                url = p.payload.get("url", "")
                if p.result.startswith("[error]") or p.result.startswith("[refused]"):
                    blocks.append(f"[read of {url}]\n{p.result[:1500]}")
                elif is_thin_read(p.result):
                    blocks.append(
                        f"[page you asked to read: {url} — but it was only a front "
                        f"door / browser warning, with no real content]\n{p.result[:400]}"
                    )
                else:
                    blocks.append(f"[page you asked to read: {url}]\n{p.result[:3500]}")
            cont_extra = "\n\n".join(blocks) + _BROWSE_RETRY_NOTE
            if thin:
                cont_extra += _BROWSE_THIN_NOTE
            if stall and not stall_nudged:
                stall_nudged = True
                cont_extra += _STALL_NUDGE_NOTE
            cont_messages = build_messages(
                user_input,
                conversation=history,
                extra_context="\n\n".join(c for c in (self_context, cont_extra) if c),
                image=image,
            )
            chunks.append("\n\n")
            yield "\n\n"
            pass_start = len("".join(chunks))
            filt3 = _BrowseStreamFilter()
            async for chunk in filt3.clean(self.provider.stream_chat(cont_messages)):
                chunks.append(chunk)
                yield chunk
            raws.append(filt3.raw())
            last_pass_text = clean_reply("".join(chunks)[pass_start:])
            await self._propose_all_from(filt3.raw(), conversation_id, on_activity)

        # Mira chose to end a first meeting: the marker is suppressed from the
        # streamed text (the filter), but its presence is surfaced to the
        # websocket so it can close the meeting the moment she does.
        self._meeting_ended = any(_MEETING_END_RE.search(r) for r in raws)

        reply = clean_reply("".join(chunks))
        if not reply:
            raw_all = "\n\n".join(raws)
            if self._meeting_ended:
                # The only thing she wrote was her end marker — still close the
                # meeting with a quiet line rather than an apology.
                reply = "I think I've heard enough for today."
            elif self._proposals:
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
                    elif p.kind == "web_search":
                        bits.append("to search the web")
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
        elif (
            len(self.last_reply.strip()) >= 40
            and not self.last_reply.startswith("I asked ")
        ):
            # Any page she actually read this turn is a source she relied on,
            # whether its text was folded into her answer or not — but a page
            # that only came back as a front door is not a real source.
            reads = [
                p
                for p in self._proposals
                if p.kind == "browse_url"
                and p.result is not None
                and not (p.result.startswith("[error]") or p.result.startswith("[refused]"))
                and not is_thin_read(p.result)
            ]
            if reads:
                self._save_browse_document(conversation_id, reads)

        schedule_archive_write(get_settings().mira_archive_path, self.user_id)
        schedule_digest(self.provider, conversation_id, self.user_id, user_input, reply, history)
