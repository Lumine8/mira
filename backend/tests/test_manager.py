import asyncio

import pytest

from app.models import Conversation, Message
from app.services.ai.fake import FakeProvider
from app.services.conversation import manager as manager_module
from app.services.conversation.manager import (
    _BROWSE_RE,
    _CONTROL_RE,
    _LISTEN_RE,
    _READ_RE,
    _REMIND_RE,
    _RUN_RE,
    _SELFEDIT_RE,
    ConversationManager,
    _BrowseStreamFilter,
)


def test_read_regex_extracts_path_and_reason() -> None:
    raw = "I'd like to look at something [[read|C:\\Users\\sanka\\Downloads\\notes.txt|to see what's in there]] please."
    match = _READ_RE.search(raw)
    assert match is not None
    assert match.group("path") == "C:\\Users\\sanka\\Downloads\\notes.txt"
    assert match.group("reason") == "to see what's in there"


def test_remind_regex_extracts_title_when_reason() -> None:
    raw = "I'll keep it [[remind|call the dentist|tomorrow at 9am|the tooth]] for you."
    match = _REMIND_RE.search(raw)
    assert match is not None
    assert match.group("title") == "call the dentist"
    assert match.group("when") == "tomorrow at 9am"
    assert match.group("reason") == "the tooth"


def test_remind_regex_ignores_plain_text() -> None:
    assert _REMIND_RE.search("remind me about dinner, ok?") is None


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

    def get(self, model, pk):
        return self.conversation if model is Conversation and pk == self.conversation.id else None

    def add(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if isinstance(obj, Message):
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
    web_window_open = True
    mira_browse_allowed_domains = ""
    mira_money_deny_domains = ""
    mira_money_deny_commands = ""


class _WebSettings(_ResearchSettings):
    pass


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
    # The continuation asks for a review grounded in the actual search protocol
    # and real screening decisions, not a recited template.
    assert "real numbers from the header" in cont_text
    assert "screening you just did" in cont_text
    assert "by first author and year" in cont_text
    assert "at least fifteen" in cont_text

    assert "Let me search the record." in mgr.last_reply
    assert "Here is the document on DNA replication based on the papers." in mgr.last_reply

    proposals = mgr.proposals()
    assert len(proposals) == 1
    assert proposals[0].kind == "research_query"
    assert proposals[0].status == "approved"
    assert proposals[0].delivered is True


@pytest.mark.asyncio
async def test_web_search_runs_and_continues_in_same_reply(monkeypatch) -> None:
    """Web search runs on its own (no approval) and its results are folded into
    the SAME reply via a continuation pass — she answers from the links without
    the voice having to nudge again."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _WebSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _WebSettings())
    monkeypatch.setattr(
        "app.services.tools.service.ToolService._render_web_search",
        lambda self, query: "1. Portland weather\n   Sunny today\n   https://weather.example/portland",
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 43
    session = RecordingSession(conv)

    provider = FakeProvider(
        [
            "I can search the open web. [[web|weather in Portland|check today]]",
            "Here is what the search found: Portland is sunny today.",
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    streamed: list[str] = []
    async for token in mgr.generate_reply(
        43,
        "what is the weather in Portland?",
        source="text",
    ):
        streamed.append(token)

    joined = "".join(streamed)
    assert "[[web" not in joined
    assert "I can search the open web." in joined
    assert "Here is what the search found" in joined

    assert len(provider._calls) == 2
    cont_text = "\n".join(m.get("content", "") for m in provider._calls[1])
    assert "Sunny today" in cont_text
    assert "web search: weather in Portland" in cont_text
    assert "A moment ago, in the same message" in cont_text

    proposals = mgr.proposals()
    assert len(proposals) == 1
    assert proposals[0].kind == "web_search"
    assert proposals[0].status == "approved"
    assert proposals[0].delivered is True


class _BrowseSettings:
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
    mira_browse_autonomous = True


@pytest.mark.asyncio
async def test_blocked_page_keeps_trying_another_source(monkeypatch) -> None:
    """When a page she asked to read is refused, she keeps trying another
    source in the SAME reply instead of stopping at the blocked site."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _BrowseSettings())

    def fake_fetch(self, url: str) -> str:
        if "blocked" in url:
            return "[error] 403 for " + url
        return "A bull market is a sustained rise in the price of stocks."

    monkeypatch.setattr(
        "app.services.tools.service.ToolService._fetch_browse",
        fake_fetch,
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)

    provider = FakeProvider(
        [
            "Let me look that up. [[browse|https://blocked.example/page|to understand the bull market]]",
            ("[[browse|https://opens.example/bull-market|to read the real article]] "
            "A bull market is a sustained rise in prices, per the source."),
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)
    activities: list[str] = []

    async def on_activity(label: str) -> None:
        activities.append(label)

    streamed: list[str] = []
    async for token in mgr.generate_reply(
        42,
        "what is a bull market? look it up",
        source="text",
        on_activity=on_activity,
    ):
        streamed.append(token)

    joined = "".join(streamed)
    assert "[[browse" not in joined
    assert "Let me look that up." in joined
    assert "A bull market is a sustained rise in prices, per the source." in joined
    assert any("looking for another source" in a for a in activities)

    # The retry pass showed her the refusal and pushed her toward another source.
    assert len(provider._calls) == 2
    cont_text = "\n".join(m.get("content", "") for m in provider._calls[1])
    assert "blocked.example/page" in cont_text
    assert "another reliable source" in cont_text

    proposals = mgr.proposals()
    assert len(proposals) == 2
    blocked = next(p for p in proposals if "blocked" in p.payload["url"])
    opened = next(p for p in proposals if "opens" in p.payload["url"])
    assert blocked.status == "approved"
    assert blocked.delivered is True  # handled in-reply, not re-injected
    assert blocked.result.startswith("[error]")
    assert opened.status == "approved"
    assert opened.result.startswith("A bull market")


@pytest.mark.asyncio
async def test_front_door_read_keeps_trying_a_different_source(monkeypatch) -> None:
    """A page that fetches but holds no real content — a browser check or pure
    navigation — does not count as finding the information: she keeps trying a
    DIFFERENT source instead of ending on a front door."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _BrowseSettings())

    def fake_fetch(self, url: str) -> str:
        if "devpost" in url:
            return (
                "New & upcoming hackathons We've detected that you are using an "
                "unsupported browser. Log in Sign up Join a hackathon Host a "
                "hackathon Projects Resources"
            )
        return "Hackathon listings: the closest upcoming events are SolarHack in "
        "Bengaluru on September 6 and the annual climate sprint in October."

    monkeypatch.setattr(
        "app.services.tools.service.ToolService._fetch_browse",
        fake_fetch,
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 44
    session = RecordingSession(conv)

    provider = FakeProvider(
        [
            "Let me check. [[browse|https://devpost.com/hackathons|to list upcoming hackathons]]",
            "[[browse|https://hackathons.example/upcoming|to list the actual events]]",
            ("Here they are: SolarHack in Bengaluru on September 6, and a climate "
            "sprint in October."),
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)
    activities: list[str] = []

    async def on_activity(label: str) -> None:
        activities.append(label)

    async for _ in mgr.generate_reply(
        44,
        "research upcoming hackathons",
        source="text",
        on_activity=on_activity,
    ):
        pass

    joined = mgr.last_reply
    # The front door was a dead end, but the turn went on to a real listing.
    assert "SolarHack in Bengaluru" in joined
    assert joined.rstrip().endswith("in October.")
    assert len(provider._calls) == 3
    # The continuation warned her the devpost page was a front door.
    cont_text = "\n".join(m.get("content", "") for m in provider._calls[1])
    assert "front door" in cont_text
    assert "Do not propose that same URL again" in cont_text
    assert any("looking for another source" in a for a in activities)

    proposals = mgr.proposals()
    front_door = next(p for p in proposals if "devpost" in p.payload["url"])
    real = next(p for p in proposals if "hackathons.example" in p.payload["url"])
    assert front_door.delivered is True
    assert real.delivered is True


@pytest.mark.asyncio
async def test_stall_reply_is_nudged_into_proposing_the_next_page(monkeypatch) -> None:
    """A reply that only promises to keep looking — 'I'll try to find a page' —
    is not allowed to end the turn: she is nudged to actually propose the next
    page, and the answer keeps going until it is real."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _BrowseSettings())

    def fake_fetch(self, url: str) -> str:
        if "devpost" in url:
            return (
                "New & upcoming hackathons We've detected that you are using an "
                "unsupported browser. Log in Sign up Join a hackathon."
            )
        return "The list: SolarHack on September 6 in Bengaluru, climate sprint in October."

    monkeypatch.setattr(
        "app.services.tools.service.ToolService._fetch_browse",
        fake_fetch,
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 45
    session = RecordingSession(conv)

    provider = FakeProvider(
        [
            "Let me check. [[browse|https://devpost.com/hackathons|to list upcoming hackathons]]",
            ("The page I looked at was just a front door — it had the menus and "
            "the login buttons, but it didn't actually list any specific events. "
            "I'll try to find a page that actually shows the listings."),
            "[[browse|https://hackathons.example/upcoming|to list the actual events]]",
            ("Here they are: SolarHack in Bengaluru on September 6, and a climate "
            "sprint in October."),
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)
    activities: list[str] = []

    async def on_activity(label: str) -> None:
        activities.append(label)

    async for _ in mgr.generate_reply(
        45,
        "research upcoming hackathons",
        source="text",
        on_activity=on_activity,
    ):
        pass

    joined = mgr.last_reply
    # The stall did not end the turn — it reads as the honest journey and lands
    # on the real answer.
    assert "SolarHack in Bengaluru" in joined
    assert joined.rstrip().endswith("in October.")
    assert len(provider._calls) == 4
    # The nudge asked her to actually propose the next page.
    nudge_text = "\n".join(m.get("content", "") for m in provider._calls[2])
    assert "Do not promise" in nudge_text
    assert "[[browse|" in nudge_text
    assert any("looking for another source" in a for a in activities)


def test_is_thin_read_spots_front_doors_and_warnings() -> None:
    assert manager_module.is_thin_read(
        "New & upcoming hackathons We've detected that you are using an "
        "unsupported browser. Please upgrade your browser. Log in Sign up"
    )
    assert manager_module.is_thin_read(
        "This page requires JavaScript. Please enable JavaScript to continue."
    )
    assert not manager_module.is_thin_read(
        "A bull market occurs when financial markets experience a decline of 20% "
        "or more, and the article explains the indicators traders watch."
    )


def test_is_stall_catches_different_path_promises() -> None:
    """'I'll try a different path' and its close variants are promises to keep
    looking, not answers — the turn must not end on them."""
    for text in [
        ("I'll try a different path. Devpost isn't letting me in, so I'll check "
        "Major League Hacking. They usually have a better map of what's coming up."),
        "I'll try another way to get the answer.",
        "Let me look somewhere else for a listing.",
        "I'll check another site that shows events.",
        "I'm going to try a different source.",
        "Looking elsewhere for a page that lists them.",
    ]:
        assert manager_module.is_stall(text), text
    # A genuine answer is not a stall.
    assert not manager_module.is_stall(
        "Here they are: SolarHack in Bengaluru on September 6, and a climate "
        "sprint in October."
    )


@pytest.mark.asyncio
async def test_stall_never_ends_turn_with_fresh_page_undelivered(monkeypatch) -> None:
    """Regression: Mira ends on 'I'll try a different path' while a real page
    (MLH) has already been fetched. The stall must keep the turn alive so the
    fetched page is read in the SAME reply — never delivered=False forever."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _BrowseSettings())

    def fake_fetch(self, url: str) -> str:
        if "devpost" in url:
            return (
                "New & upcoming hackathons We've detected that you are using an "
                "unsupported browser. Log in Sign up Join a hackathon."
            )
        return "2025 Season Schedule // Major League Hacking SolarHack on September 6 in Bengaluru, climate sprint in October."

    monkeypatch.setattr(
        "app.services.tools.service.ToolService._fetch_browse",
        fake_fetch,
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 46
    session = RecordingSession(conv)

    provider = FakeProvider(
        [
            ("I'll try a different path. Devpost isn't letting me in, so I'll check "
            "Major League Hacking. They usually have a better map of what's coming "
            "up. [[browse|https://devpost.com/hackathons|to find the actual list of "
            "upcoming hackathons]][[browse|https://mlh.io/seasons/2025/events|to see "
            "the MLH event calendar]]"),
            ("Here they are: SolarHack in Bengaluru on September 6, and a climate "
            "sprint in October."),
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)
    activities: list[str] = []

    async def on_activity(label: str) -> None:
        activities.append(label)

    streamed: list[str] = []
    async for token in mgr.generate_reply(
        46,
        "can you try again?",
        source="text",
        on_activity=on_activity,
    ):
        streamed.append(token)

    joined = "".join(streamed)
    # The promise did not end the turn: the fetched MLH page was read and answered
    # in the same reply — exactly two provider passes, no wasted nudge call.
    assert "Here they are: SolarHack in Bengaluru" in joined
    assert joined.rstrip().endswith("in October.")
    assert len(provider._calls) == 2
    cont_text = "\n".join(m.get("content", "") for m in provider._calls[1])
    assert "mlh.io" in cont_text
    assert "SolarHack on September 6" in cont_text

    proposals = mgr.proposals()
    front_door = next(p for p in proposals if "devpost" in p.payload["url"])
    real = next(p for p in proposals if "mlh.io" in p.payload["url"])
    assert front_door.delivered is True
    assert real.delivered is True
    assert "SolarHack on September 6" in real.result
    assert any("looking for another source" in a for a in activities)


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
    assert "*by Mira" in content
    assert "literature review" in content
    assert mgr.last_reply in content

    # The voice first hears she is writing the paper, then that it exists.
    assert [o["type"] for o, _ in sent] == ["document_creating", "document_created"]
    creating, created = sent
    assert creating[0] == {
        "type": "document_creating",
        "conversation_id": 42,
    }
    obj, user_id = created
    assert user_id == 1
    assert obj["type"] == "document_created"
    assert obj["name"] == "research-dna-replication"
    assert obj["author"] == "mira"
    assert obj["conversation_id"] == 42


@pytest.mark.asyncio
async def test_web_research_ends_with_document_on_her_shelf(monkeypatch) -> None:
    """A page she asked to read, read back to her and answered from, is saved
    onto her documents shelf as a paper too."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _BrowseSettings())

    monkeypatch.setattr(
        "app.services.tools.service.ToolService._fetch_browse",
        lambda self, url: "A bull market is a sustained rise in the price of stocks.",
    )

    saved: list[tuple[str, str]] = []
    sent: list[tuple[dict, int]] = []

    class _FakeDocs:
        def __init__(self, db, *, user_id) -> None:
            pass

        def create_mira(self, title, content):
            saved.append((title, content))
            return {"name": "research-bull-market", "author": "mira"}

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
            "[[browse|https://opens.example/bull-market|to understand the bull market]]",
            ("A bull market is a sustained rise in prices, and a bear market is the opposite. "
            "Traders look for a sustained 20% move to call it a trend, and the articles explain "
            "that the key indicators are market breadth, moving averages, and investor sentiment. "
            "Understanding both shapes helps a trader time entries and recognize reversals."),
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    async for _ in mgr.generate_reply(42, "research bullish and bearish", source="text"):
        pass

    assert len(saved) == 1
    title, content = saved[0]
    assert title == "Research: Understand the bull market"
    assert "web research" in content
    assert mgr.last_reply in content
    # The paper cites the pages it actually read.
    assert "## Sources" in content
    assert "https://opens.example/bull-market" in content

    assert [o["type"] for o, _ in sent] == ["document_created"]
    obj, user_id = sent[0]
    assert user_id == 1
    assert obj["name"] == "research-bull-market"
    assert obj["author"] == "mira"
    assert obj["conversation_id"] == 42


@pytest.mark.asyncio
async def test_web_research_creates_paper_when_she_answers_alongside_the_read(
    monkeypatch,
) -> None:
    """If she answers in the same breath as proposing a page, the read still
    counts as a source she relied on, so a paper lands on the shelf with it."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _BrowseSettings())
    monkeypatch.setattr(
        "app.services.tools.service.ToolService._fetch_browse",
        lambda self, url: "Tides are caused by the moon's gravity pulling on the oceans.",
    )

    saved: list[tuple[str, str]] = []
    sent: list[tuple[dict, int]] = []

    class _FakeDocs:
        def __init__(self, db, *, user_id) -> None:
            pass

        def create_mira(self, title, content):
            saved.append((title, content))
            return {"name": "research-verify-the-cause-of-tides", "author": "mira"}

    monkeypatch.setattr(manager_module, "DocumentService", _FakeDocs)
    monkeypatch.setattr(
        manager_module,
        "broadcast_later",
        lambda obj, user_id: sent.append((obj, user_id)),
    )

    conv = Conversation(kind="text", user_id=1)
    conv.id = 43
    session = RecordingSession(conv)
    provider = FakeProvider(
        [
            ("The moon's gravity pulls on the ocean, and that pull is what we "
            "feel as the tide. [[browse|https://oceans.example/tides|to verify "
            "the cause of tides]]"),
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    async for _ in mgr.generate_reply(43, "research what causes tides", source="text"):
        pass

    assert len(saved) == 1
    title, content = saved[0]
    assert title == "Research: Verify the cause of tides"
    assert mgr.last_reply in content
    assert "## Sources" in content
    assert "https://oceans.example/tides" in content
    assert [o["type"] for o, _ in sent] == ["document_created"]


@pytest.mark.asyncio
async def test_research_document_cites_the_papers(monkeypatch) -> None:
    """A finished literature review lands on the shelf with a proper numbered
    reference list pulled from the search blocks — author, year, title, journal,
    and the live link."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(
        "app.services.tools.service.ToolService._render_research",
        lambda self, query: (
            "Search protocol: index = Europe PMC\n"
            "1. The Folding of Amyloid Fibrils\n"
            "   Jane Doe et al.\n"
            "   Nature, 2024, cited 12 times\n"
            "   Amyloid proteins fold wrong.\n"
            "   https://europepmc.org/article/PMC/123456\n"
            "2. A Second Paper About Cells\n"
            "   John Smith et al.\n"
            "   Science, 2023, cited 4 times\n"
            "   Cells do interesting things.\n"
            "   https://doi.org/10.1000/xyz\n"
        ),
    )

    saved: list[tuple[str, str]] = []

    class _FakeDocs:
        def __init__(self, db, *, user_id) -> None:
            pass

        def create_mira(self, title, content):
            saved.append((title, content))
            return {"name": "research-amyloid", "author": "mira"}

    monkeypatch.setattr(manager_module, "DocumentService", _FakeDocs)
    monkeypatch.setattr(manager_module, "broadcast_later", lambda obj, user_id: None)

    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)
    provider = FakeProvider(
        [
            "Let me search the record. [[research|amyloid folding|latest papers]]",
            "Here is the review based on the papers.",
        ]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    async for _ in mgr.generate_reply(42, "research amyloid", source="text"):
        pass

    assert len(saved) == 1
    _, content = saved[0]
    assert "## References" in content
    assert "1. Jane Doe et al. (2024). \u201cThe Folding of Amyloid Fibrils\u201d. Nature." in content
    assert "https://europepmc.org/article/PMC/123456" in content
    assert "2. John Smith et al. (2023). \u201cA Second Paper About Cells\u201d. Science." in content


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


@pytest.mark.asyncio
async def test_meeting_mode_suppresses_all_tools(monkeypatch) -> None:
    """A first meeting is tool-free: Mira's tool intents must never turn into
    proposals or saved documents while the door is open, and no continuation
    pass may run on the guest's behalf."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _ResearchSettings())

    saved: list[tuple[str, str]] = []

    class _FakeDocs:
        def __init__(self, db, *, user_id) -> None:
            pass

        def create_mira(self, title, content):
            saved.append((title, content))
            return {"name": "x", "author": "mira"}

    monkeypatch.setattr(manager_module, "DocumentService", _FakeDocs)
    monkeypatch.setattr(manager_module, "broadcast_later", lambda obj, user_id: None)

    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)
    provider = FakeProvider(
        ["Let me look into that. [[research|amyloid folding|latest papers]]"]
    )
    mgr = ConversationManager(session, provider, user_id=1)
    mgr.meeting_mode = True

    streamed: list[str] = []
    async for token in mgr.generate_reply(42, "research amyloid", source="text"):
        streamed.append(token)

    assert mgr.meeting_mode is True
    assert mgr.proposals() == []
    assert saved == []
    assert len(provider._calls) == 1
    assert "Let me look into that." in mgr.last_reply
    assert "[[research" not in "".join(streamed)


def test_meeting_end_regex_matches_the_marker() -> None:
    assert manager_module._MEETING_END_RE.search(
        "I think I've heard enough for today. [[end-first-meeting]]"
    ) is not None
    assert manager_module._MEETING_END_RE.search("an ordinary reply") is None


def test_meeting_end_marker_is_suppressed_from_visible_stream() -> None:
    filt = _BrowseStreamFilter()

    async def _stream():
        yield "I think I've heard enough for today. [[end-first-meeting]]"

    async def _run() -> str:
        out: list[str] = []
        async for token in filt.clean(_stream()):
            out.append(token)
        return "".join(out)

    import asyncio

    assert asyncio.run(_run()) == "I think I've heard enough for today. "
    assert "end-first-meeting" in filt.raw()


@pytest.mark.asyncio
async def test_meeting_end_sentinel_sets_flag_and_stays_hidden(monkeypatch) -> None:
    monkeypatch.setattr(manager_module, "get_settings", lambda: _Settings())
    conv = Conversation(kind="text", user_id=1)
    conv.id = 42
    session = RecordingSession(conv)

    provider = FakeProvider(["I think I've heard enough for today. [[end-first-meeting]]"])
    mgr = ConversationManager(session, provider, user_id=1)

    streamed: list[str] = []
    async for token in mgr.generate_reply(42, "one more thing", source="text"):
        streamed.append(token)

    assert mgr._meeting_ended is True
    assert "[[end-first-meeting]]" not in mgr.last_reply
    assert "[[end-first-meeting]]" not in "".join(streamed)
    assert "I think I've heard enough for today." in mgr.last_reply

def test_control_regex_extracts_action_target_reason() -> None:
    raw = "I want to play something [[control|open|Spotify|she wants music playing]]."
    match = _CONTROL_RE.search(raw)
    assert match is not None
    assert match.group("action") == "open"
    assert match.group("target") == "Spotify"
    assert match.group("reason") == "she wants music playing"


def test_control_regex_allows_empty_target() -> None:
    raw = "Lower it a notch [[control|volume_down||lower the volume]]."
    match = _CONTROL_RE.search(raw)
    assert match is not None
    assert match.group("action") == "volume_down"
    assert match.group("target") == ""
    assert match.group("reason") == "lower the volume"


def test_control_regex_ignores_plain_text() -> None:
    assert _CONTROL_RE.search("no markers here") is None


def test_control_regex_case_insensitive() -> None:
    raw = "[[CONTROL|Mute||quiet the room]]"
    match = _CONTROL_RE.search(raw)
    assert match is not None
    assert match.group("action") == "Mute"


@pytest.mark.asyncio
async def test_control_intent_becomes_pending_proposal(monkeypatch) -> None:
    """A [[control|...]] intent Mira writes becomes a host_control PendingChange
    awaiting approval — never executed by the backend itself."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _ResearchSettings())

    conv = Conversation(id=42, kind="text", user_id=1)
    session = RecordingSession(conv)
    provider = FakeProvider(
        ["Let me lower that for you. [[control|volume_down||the music is too loud]]"]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    streamed: list[str] = []
    async for token in mgr.generate_reply(42, "the music is too loud", source="text"):
        streamed.append(token)

    assert "[[control" not in "".join(streamed)
    proposals = mgr.proposals()
    controls = [p for p in proposals if p.kind == "host_control"]
    assert len(controls) == 1
    assert controls[0].payload["action"] == "volume_down"
    assert controls[0].status == "pending"


@pytest.mark.asyncio
async def test_control_intent_rejects_unsafe_target(monkeypatch) -> None:
    """A control proposal with a dangerous target is dropped, not proposed —
    the reply itself still lands."""
    import app.services.tools.service as tools_module

    monkeypatch.setattr(manager_module, "get_settings", lambda: _ResearchSettings())
    monkeypatch.setattr(tools_module, "get_settings", lambda: _ResearchSettings())

    conv = Conversation(id=43, kind="text", user_id=1)
    session = RecordingSession(conv)
    provider = FakeProvider(
        ["Let me open that. [[control|open|notepad.exe; whoami||open it]]"]
    )
    mgr = ConversationManager(session, provider, user_id=1)

    async for _ in mgr.generate_reply(43, "open that", source="text"):
        pass

    controls = [p for p in mgr.proposals() if p.kind == "host_control"]
    assert controls == []
