import asyncio

import pytest

from app.models import Conversation, Message
from app.services.ai.fake import FakeProvider
from app.services.conversation import manager as manager_module
from app.services.conversation.manager import ConversationManager
from app.services.conversation.manager import (
    _BROWSE_RE,
    _BrowseStreamFilter,
    _LISTEN_RE,
    _READ_RE,
    _RUN_RE,
    _SELFEDIT_RE,
)


def test_read_regex_extracts_path_and_reason() -> None:
    raw = "I'd like to look at something [[read|C:\\Users\\sanka\\Downloads\\notes.txt|to see what's in there]] please."
    match = _READ_RE.search(raw)
    assert match is not None
    assert match.group("path") == "C:\\Users\\sanka\\Downloads\\notes.txt"
    assert match.group("reason") == "to see what's in there"


def test_read_regex_ignores_plain_text() -> None:
    assert _READ_RE.search("no markers here") is None


def test_run_regex_extracts_reason_and_command() -> None:
    raw = "I'd like to check something [[run|see the Dhan exports folder|Get-ChildItem \"$HOME\\Downloads\"]] please."
    match = _RUN_RE.search(raw)
    assert match is not None
    assert match.group("reason") == "see the Dhan exports folder"
    assert match.group("command") == 'Get-ChildItem "$HOME\\Downloads"'
    assert "see the Dhan exports folder" not in match.group("command")


def test_run_regex_allows_pipes_in_command() -> None:
    raw = "[[run|count my processes|Get-Process | Measure-Object]]"
    match = _RUN_RE.search(raw)
    assert match is not None
    assert match.group("command") == "Get-Process | Measure-Object"


def test_run_regex_ignores_plain_text() -> None:
    assert _RUN_RE.search("no markers here") is None


def test_browse_regex_extracts_url_and_reason() -> None:
    raw = "I'd like to see this [[browse|https://example.com|to understand what it is]] anyway."
    match = _BROWSE_RE.search(raw)
    assert match is not None
    assert match.group("url") == "https://example.com"
    assert match.group("reason") == "to understand what it is"


def test_browse_regex_ignores_plain_text() -> None:
    assert _BROWSE_RE.search("no markers here") is None


def test_listen_regex_extracts_title_artist_reason() -> None:
    raw = "I'd like to hear this [[listen|Clocks|Coldplay|to feel what the voice is hearing]] please."
    match = _LISTEN_RE.search(raw)
    assert match is not None
    assert match.group("title") == "Clocks"
    assert match.group("artist") == "Coldplay"
    assert match.group("reason") == "to feel what the voice is hearing"


def test_listen_regex_ignores_plain_text() -> None:
    assert _LISTEN_RE.search("no markers here") is None


def test_selfedit_regex_extracts_path_summary_content() -> None:
    raw = (
        "I think this rule is too rigid. "
        "[[selfedit|data/self/principles.md|a softer wording|"
        "- Observe carefully.\\n- Revise when evidence changes.]]"
    )
    match = _SELFEDIT_RE.search(raw)
    assert match is not None
    assert match.group("path") == "data/self/principles.md"
    assert match.group("summary") == "a softer wording"
    assert "Observe carefully" in match.group("content")
    assert "Revise when evidence changes" in match.group("content")


def test_selfedit_regex_ignores_plain_text() -> None:
    assert _SELFEDIT_RE.search("no self edits here") is None


def test_selfedit_regex_accepts_code_with_brackets() -> None:
    raw = (
        "I'll build the browser route now. "
        "[[selfedit|backend/app/api/routes/browser.py|add the browse view route|"
        "from fastapi import APIRouter\\n"
        "router = APIRouter(tags=[\"mira\"])\\n"
        "@router.get(\"/mira/browse/view\")\\n"
        "async def view(url: str):\\n"
        "    items = [\"X-Frame-Options\", \"Content-Security-Policy\"]\\n"
        "    return HTMLResponse(html)]]"
    )
    match = _SELFEDIT_RE.search(raw)
    assert match is not None
    assert match.group("path") == "backend/app/api/routes/browser.py"
    assert "APIRouter(tags=[\"mira\"])" in match.group("content")
    assert "X-Frame-Options" in match.group("content")


async def _clean(tokens: list[str]) -> str:
    filt = _BrowseStreamFilter()
    out = []
    async for token in filt.clean(_aiter(tokens)):
        out.append(token)
    return "".join(out)


async def _aiter(items: list[str]):
    for item in items:
        yield item


def test_stream_filter_suppresses_marker_across_tokens() -> None:
    tokens = ["Hello. ", "I want to look ", "at [[browse|https://x.co", "|reason]] more.", " Bye"]
    cleaned = asyncio.run(_clean(tokens))
    assert "browse|" not in cleaned
    assert "https://x.co" not in cleaned
    assert "Hello." in cleaned
    assert "more." in cleaned


def test_stream_filter_keeps_plain_text() -> None:
    tokens = ["Just a", " normal", " message."]
    cleaned = asyncio.run(_clean(tokens))
    assert cleaned == "Just a normal message."


class RecordingSession:
    """Mini in-memory stand-in for the SQLAlchemy session that mirrors the real
    ordering behavior: recent_messages reflects messages already committed, so
    history must be read *before* the current user message is stored."""

    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation
        self.messages: list[Message] = []
        self._next_id = 1

    def get(self, model, pk):  # noqa: N802 - SQLAlchemy session API
        return self.conversation if model is Conversation and pk == self.conversation.id else None

    def add(self, obj: object) -> None:
        if isinstance(obj, Message):
            obj.id = self._next_id
            self._next_id += 1
            self.messages.append(obj)

    def commit(self) -> None:
        pass

    def refresh(self, _obj: object) -> None:
        pass

    def execute(self, _stmt: object) -> object:
        rows = sorted(
            (m for m in self.messages if m.conversation_id == self.conversation.id),
            key=lambda m: m.id,
            reverse=True,
        )

        class _Result:
            def scalars(self):
                return list(rows)

        return _Result()


class _Settings:
    self_model_enabled = False
    console_emotions_enabled = False
    mira_archive_path = ""


@pytest.mark.asyncio
async def test_current_turn_reaches_provider_exactly_once(monkeypatch) -> None:
    """Regression: the user's message used to be sent twice (once from history,
    once appended by build_messages), which is why Mira kept saying the words
    'came again' — they did. History must exclude the current turn."""
    monkeypatch.setattr(manager_module, "get_settings", lambda: _Settings())
    conv = Conversation(kind="text")
    conv.id = 42
    session = RecordingSession(conv)
    prior = [
        Message(conversation_id=42, speaker="user", content="good morning", source="text"),
        Message(conversation_id=42, speaker="mira", content="morning", source="text"),
    ]
    for i, m in enumerate(prior, 1):
        m.id = i
        session.messages.append(m)
    session._next_id = 3

    provider = FakeProvider(["A quiet reply."])
    mgr = ConversationManager(session, provider)

    async for _ in mgr.generate_reply(42, "the apple cart tipped", source="text"):
        pass

    sent = provider._calls[0]
    contents = [m["content"] for m in sent]
    assert contents.count("the apple cart tipped") == 1
    assert contents.count("good morning") == 1
    assert contents[-1] == "the apple cart tipped"
    assert contents[-2] == "morning"
