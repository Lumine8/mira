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
    conv = Conversation(kind="text", user_id=1)
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
    mgr = ConversationManager(session, provider, user_id=1)

    async for _ in mgr.generate_reply(42, "the apple cart tipped", source="text"):
        pass

    sent = provider._calls[0]
    contents = [m["content"] for m in sent]
    assert contents.count("the apple cart tipped") == 1
    assert contents.count("good morning") == 1
    assert contents[-1] == "the apple cart tipped"
    assert contents[-2] == "morning"


class _ResearchSettings:
    self_model_enabled = False
    console_emotions_enabled = False
    mira_archive_path = ""
    self_edit_roots = "."
    mira_self_write_roots = "."
    mira_self_write_deny = ""
    mira_self_write_autonomous = False
    browse_window_open = False
    host_window_open = False
    research_window_open = True
    mira_browse_allowed_domains = ""
    mira_money_deny_domains = ""
    mira_money_deny_commands = ""


@pytest.mark.asyncio
async def test_research_runs_and_continues_in_same_reply(monkeypatch) -> None:
    """Research runs on its own (no approval) and its results are folded into
    the SAME reply via a continuation pass — she delivers the document without
    the voice having to nudge again. Activity lines are streamed along the way."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(
        "app.services.tools.service.ToolService._render_research",
        lambda self, query: "First paper about DNA replication.",
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)

    provider = FakeProvider(
        [
            "Let me search the record. [[research|DNA replication|latest papers]]",
            "Here is the document on DNA replication based on the papers.",
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)
    activities: list[str] = []

    async def on_activity(label: str) -> None:
        activities.append(label)

    streamed: list[str] = []
    async for token in mgr.generate_reply(
        42,
        "research DNA replication and write a document",
        source="text",
        on_activity=on_activity,
    ):
        streamed.append(token)

    joined = "".join(streamed)
    assert "[[research" not in joined
    assert "Let me search the record." in joined
    assert "Here is the document on DNA replication" in joined
    assert activities == [
        "searching the scientific literature for DNA replication",
        "thinking",
    ]

    assert len(provider._calls) == 2
    cont_messages = provider._calls[1]
    cont_text = "\n".join(m.get("content", "") for m in cont_messages)
    assert "First paper about DNA replication." in cont_text
    assert "search of the scientific record: DNA replication" in cont_text
    # The continuation instructs a proper review: hypotheses and breadth.
    assert "null hypothesis (H0)" in cont_text
    assert "alternative hypothesis (H1)" in cont_text
    assert "at least fifteen" in cont_text

    assert "Let me search the record." in mgr.last_reply
    assert "Here is the document on DNA replication based on the papers." in mgr.last_reply

    proposals = mgr.proposals()
    assert len(proposals) == 1
    assert proposals[0].kind == "research_query"
    assert proposals[0].status == "approved"
    assert proposals[0].delivered is True


@pytest.mark.asyncio
async def test_research_ends_with_document_on_her_shelf(monkeypatch) -> None:
    """A finished research run hands over its review as a mira document and
    broadcasts document_created so the voice can open the paper beside the
    conversation."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(
        "app.services.tools.service.ToolService._render_research",
        lambda self, query: "First paper about DNA replication.",
    )

    saved: list[tuple[str, str]] = []
    sent: list[tuple[dict, int]] = []

    class _FakeDocs:
        def __init__(self, db, *, user_id) -> None:
            pass

        def create_mira(self, title, content):
            saved.append((title, content))
            return {"name": "research-dna-replication", "author": "mira"}

    monkeypatch.setattr(manager_module, "DocumentService", _FakeDocs)
    monkeypatch.setattr(
        manager_module,
        "broadcast_later",
        lambda obj, user_id: sent.append((obj, user_id)),
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)
    provider = FakeProvider(
        [
            "Let me search the record. [[research|DNA replication|latest papers]]",
            "Here is the document on DNA replication based on the papers.",
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    async for _ in mgr.generate_reply(42, "research DNA replication", source="text"):
        pass

    assert len(saved) == 1
    title, content = saved[0]
    assert title == "Research: DNA replication"
    assert content.startswith("# Research: DNA replication")
    assert mgr.last_reply in content

    assert len(sent) == 1
    obj, user_id = sent[0]
    assert user_id == 1
    assert obj["type"] == "document_created"
    assert obj["name"] == "research-dna-replication"
    assert obj["author"] == "mira"
    assert obj["conversation_id"] == 42


@pytest.mark.asyncio
async def test_research_wall_closed_stays_pending_no_continuation(monkeypatch) -> None:
    """With the research wall closed, a search stays pending and no second pass
    runs — the old approved-gate behavior is intact as a fallback."""
    import app.services.tools.service as tools_module

    class Closed(_ResearchSettings):
        research_window_open = False

    monkeypatch.setattr(manager_module, "get_settings", lambda: Closed())
    monkeypatch.setattr(tools_module, "get_settings", lambda: Closed())

    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)

    provider = FakeProvider(["[[research|DNA replication|latest papers]]"])
    mgr = ConversationManager(session, provider, user_id=1)

    streamed: list[str] = []
    async for token in mgr.generate_reply(42, "research DNA replication", source="text"):
        streamed.append(token)

    assert len(provider._calls) == 1
    assert mgr.last_reply == "I asked to search the scientific literature. It is yours to decide."
    proposals = mgr.proposals()
    assert len(proposals) == 1
    assert proposals[0].status == "pending"
