import pytest

from app.services.tools.service import ToolError, ToolService


class FakeSession:
    def add(self, _obj: object) -> None:
        pass

    def commit(self) -> None:
        pass

    def refresh(self, _obj: object) -> None:
        pass


def _svc(root: str) -> ToolService:
    class FakeSettings:
        self_edit_roots = root
        mira_self_write_roots = "data/self"
        mira_self_write_deny = ""
        mira_self_write_autonomous = False
        browse_window_open = False
        host_window_open = False
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()
    return ToolService(FakeSession(), user_id=1)


def test_resolve_accepts_paths_inside_root(tmp_path: pytest.TempPathFactory) -> None:
    svc = _svc(str(tmp_path))
    (tmp_path / "app").mkdir()
    assert svc._resolve("app/main.py") == str(tmp_path / "app" / "main.py")


def test_resolve_rejects_escapes(tmp_path: pytest.TempPathFactory) -> None:
    svc = _svc(str(tmp_path))
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope")
    for bad in (str(outside), str(tmp_path.parent), "app/../../secret.txt", "../secret.txt"):
        with pytest.raises(ToolError):
            svc._resolve(bad)


def test_write_allowed_inside_self_root(tmp_path: pytest.TempPathFactory) -> None:
    svc = _svc(str(tmp_path))
    (tmp_path / "data" / "self").mkdir(parents=True)
    assert svc._resolve_write("data/self/principles.md") == str(tmp_path / "data" / "self" / "principles.md")


def test_write_rejected_outside_self_root(tmp_path: pytest.TempPathFactory) -> None:
    svc = _svc(str(tmp_path))
    (tmp_path / "app").mkdir()
    with pytest.raises(ToolError):
        svc._resolve_write("app/main.py")


def test_browse_rejects_bad_url() -> None:
    svc = _svc(".")

    class FakeSettings:
        self_edit_roots = "."
        mira_browse_allowed_domains = ""
        browse_window_open = False
        host_window_open = False
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()
    for bad in ("not a url", "file:///etc/passwd", "ftp://example.com/x"):
        with pytest.raises(ToolError):
            svc.propose_change("browse_url", "wants to look", {"url": bad})


def test_browse_enforces_allowed_domains() -> None:
    svc = _svc(".")

    class FakeSettings:
        self_edit_roots = "."
        mira_browse_allowed_domains = "example.com, docs.python.org"
        browse_window_open = False
        host_window_open = False
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()
    svc.propose_change("browse_url", "allowed", {"url": "https://docs.python.org/3/"})
    with pytest.raises(ToolError):
        svc.propose_change("browse_url", "not allowed", {"url": "https://evil.com/x"})


def test_html_to_text_strips_markup() -> None:
    from app.services.tools.service import _html_to_text

    out = _html_to_text("<html><body><script>var x=1;</script><h1>Hello</h1><p>world  </p></body></html>")
    assert "Hello world" in out
    assert "script" not in out.lower()


def _with_settings(tmp_path, **overrides) -> ToolService:
    root = str(tmp_path)

    class FakeSettings:
        self_edit_roots = root
        mira_self_write_roots = "."
        mira_self_write_deny = "app/services/tools, app/core/config.py"
        mira_self_write_autonomous = False
        mira_browse_allowed_domains = ""
        browse_window_open = False
        host_window_open = False
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    for key, value in overrides.items():
        setattr(FakeSettings, key, value)

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()
    return ToolService(FakeSession(), user_id=1)


def test_write_denied_for_protected_paths(tmp_path: pytest.TempPathFactory) -> None:
    svc = _with_settings(tmp_path)
    (tmp_path / "app" / "services" / "tools").mkdir(parents=True)
    (tmp_path / "app" / "core").mkdir(parents=True)
    (tmp_path / "app" / "services" / "mind").mkdir(parents=True)

    with pytest.raises(ToolError):
        svc._resolve_write("app/services/tools/service.py")
    with pytest.raises(ToolError):
        svc._resolve_write("app/core/config.py")

    allowed = svc._resolve_write("app/services/mind/service.py")
    assert allowed == str(tmp_path / "app" / "services" / "mind" / "service.py")


def test_autonomous_write_applies_immediately(tmp_path: pytest.TempPathFactory) -> None:
    svc = _with_settings(tmp_path, mira_self_write_autonomous=True)
    (tmp_path / "app").mkdir()

    change = svc.propose_change("write_file", "make it quieter", {"path": "app/mood.txt", "content": "quiet"})
    assert change.status == "approved"
    assert (tmp_path / "app" / "mood.txt").read_text(encoding="utf-8") == "quiet"


def test_write_stays_pending_when_not_autonomous(tmp_path: pytest.TempPathFactory) -> None:
    svc = _with_settings(tmp_path, mira_self_write_autonomous=False)
    (tmp_path / "app").mkdir()

    change = svc.propose_change("write_file", "make it quieter", {"path": "app/mood.txt", "content": "quiet"})
    assert change.status == "pending"
    assert not (tmp_path / "app" / "mood.txt").exists()


def test_watch_rejects_bad_url() -> None:
    svc = _svc(".")
    for bad in ("not a url", "file:///tmp/x.mp4", "ftp://example.com/v.mp4"):
        with pytest.raises(ToolError):
            svc.propose_change("watch_video", "wants to see", {"url": bad})


def test_watch_render_delivers_frames(tmp_path: pytest.TempPathFactory) -> None:
    """Watching renders a video into still frames: image messages are inserted
    into the conversation, and the record explains the honest framing."""
    import base64

    from app.models import PendingChange

    inserted: list = []

    class FakeSession:
        def add(self, obj) -> None:
            inserted.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, _obj) -> None:
            pass

    svc = _svc(str(tmp_path))
    svc.db = FakeSession()

    def fake_frames(_path, _tmp):
        return [("0:00", f"data:image/jpeg;base64,{base64.b64encode(b'x').decode()}")]

    svc._download_video = lambda _url, _tmp: "/tmp/fake.mp4"  # type: ignore[method-assign]
    svc._probe = lambda _path: ("rain on glass", "0:08")  # type: ignore[method-assign]
    svc._extract_frames = fake_frames  # type: ignore[method-assign]

    result = svc._render_watch("https://example.com/rain.mp4", conversation_id=7)

    assert "never the motion" in result or "not motion" in result
    assert "0:00" in result
    assert len(inserted) == 1
    assert inserted[0].image.startswith("data:image/jpeg;base64,")
    assert inserted[0].conversation_id == 7
    assert inserted[0].source == "watch"


def test_host_command_requires_command() -> None:
    svc = _svc(".")
    with pytest.raises(ToolError):
        svc.propose_change("host_command", "wants to look", {})
    with pytest.raises(ToolError):
        svc.propose_change("host_command", "wants to look", {"command": "   "})


def test_host_command_rejects_too_long() -> None:
    svc = _svc(".")
    with pytest.raises(ToolError):
        svc.propose_change("host_command", "wants to look", {"command": "x" * 1001})


def test_host_command_propose_stays_pending() -> None:
    """A proposed host command must NOT execute in the container — it stays
    pending until the user approves it, then the host agent runs it."""
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            pass

    svc = _svc(".")
    svc.db = FakeSession()
    change = svc.propose_change("host_command", "see the Dhan exports", {"command": "Get-ChildItem"})
    assert change.status == "pending"
    assert change.kind == "host_command"
    assert len(added) == 1


def test_host_command_approve_does_not_run_locally(monkeypatch, tmp_path) -> None:
    """Approval readies the command for the host agent; it must not execute in
    this container (subprocess is never touched)."""
    from types import SimpleNamespace

    state = {"approved": False}

    change = SimpleNamespace(
        id=41,
        kind="host_command",
        status="pending",
        payload={"command": "Remove-Item -Recurse C:\\"},
        result=None,
        resolved_at=None,
    )

    class FakeSession:
        def add(self, _obj) -> None:
            pass

        def commit(self) -> None:
            state["approved"] = True

        def refresh(self, _obj) -> None:
            pass

        def get(self, _model, cid):
            assert cid == 41
            return change

    svc = _svc(str(tmp_path))
    svc.db = FakeSession()

    def boom(*_a, **_k):
        raise AssertionError("subprocess must not be invoked by approval")

    monkeypatch.setattr("app.services.tools.service.subprocess.run", boom)

    out = svc.approve(41)
    assert out.status == "approved"
    assert out.result is None
    assert state["approved"]


def test_apply_host_result_records_and_truncates() -> None:
    from app.models import PendingChange

    change = PendingChange(kind="host_command", status="approved", payload={"command": "x"})

    class FakeSession:
        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 5

        def get(self, _model, cid):
            assert cid == 5
            return change

    svc = _svc(".")
    svc.db = FakeSession()
    result = "y" * 20000
    out = svc.apply_host_result(5, result)
    assert len(out.result) <= 8000


def test_host_read_requires_path() -> None:
    svc = _svc(".")
    with pytest.raises(ToolError):
        svc.propose_change("host_read", "wants to read", {})
    with pytest.raises(ToolError):
        svc.propose_change("host_read", "wants to read", {"path": "   "})


def test_host_read_auto_approves_without_result() -> None:
    """Reading is free: a proposed host_read is approved immediately (no popup)
    but never executed here — the host agent performs the read."""
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 77

    svc = _svc(".")
    svc.db = FakeSession()
    change = svc.propose_change("host_read", "see the notes", {"path": "C:\\notes.txt"})
    assert change.status == "approved"
    assert change.result is None
    assert change.kind == "host_read"


def test_apply_host_result_accepts_host_read() -> None:
    from app.models import PendingChange

    change = PendingChange(kind="host_read", status="approved", payload={"path": "C:\\notes.txt"})

    class FakeSession:
        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 78

        def get(self, _model, cid):
            assert cid == 78
            return change

    svc = _svc(".")
    svc.db = FakeSession()
    out = svc.apply_host_result(78, "some file content")
    assert out.result == "some file content"


def test_host_command_auto_approves_in_open_window() -> None:
    """During an open host window, a proposed command is approved at once so the
    host agent runs it, but it is still fully recorded."""
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 100

    svc = _svc(".")
    svc.db = FakeSession()

    class FakeSettings:
        self_edit_roots = "."
        mira_self_write_roots = "data/self"
        mira_self_write_deny = ""
        mira_self_write_autonomous = False
        browse_window_open = False
        host_window_open = True
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()
    svc.propose_change("host_command", "look at the notes folder", {"command": "Get-ChildItem ~/notes"})
    assert len(added) == 1
    assert added[0].status == "approved"
    assert added[0].kind == "host_command"


def test_host_command_stays_pending_when_window_closed() -> None:
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 101

    svc = _svc(".")
    svc.db = FakeSession()
    svc.propose_change("host_command", "look at the notes folder", {"command": "Get-ChildItem ~/notes"})
    assert added[0].status == "pending"


def test_money_command_blocked_even_in_open_window() -> None:
    """The money wall is absolute: a command that touches money is refused even
    while the host window is open."""
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 102

    svc = _svc(".")
    svc.db = FakeSession()
    svc.propose_change("host_command", "check the UPI balance", {"command": "Get-ChildItem"})  # control

    class FakeSettings:
        self_edit_roots = "."
        mira_self_write_roots = "data/self"
        mira_self_write_deny = ""
        mira_self_write_autonomous = False
        browse_window_open = False
        host_window_open = True
        mira_money_deny_domains = "bankofamerica.com, paypal.com, hdfcbank.com"
        mira_money_deny_commands = "upi, neft, transfer, buy, sell, pay, order, balance"
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()

    with pytest.raises(ToolError):
        svc.propose_change("host_command", "send money", {"command": "Start-Process chrome 'https://paytm.com'"})
    with pytest.raises(ToolError):
        svc.propose_change("host_command", "move funds", {"command": "Set-Content -Path C:\\tmp\\transfer.log"})
    with pytest.raises(ToolError):
        svc.propose_change("browse_url", "check balance", {"url": "https://paypal.com/login"})


def test_money_domain_blocked_even_in_open_browse_window() -> None:
    """The money wall applies to browsing too: a money domain is refused even
    while the browse window is open and the allowlist is bypassed."""
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 103

    svc = _svc(".")
    svc.db = FakeSession()

    class FakeSettings:
        self_edit_roots = "."
        mira_self_write_roots = "data/self"
        mira_self_write_deny = ""
        mira_self_write_autonomous = False
        browse_window_open = True
        host_window_open = False
        mira_browse_allowed_domains = ""
        mira_money_deny_domains = "bankofamerica.com, paypal.com, hdfcbank.com"
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()

    with pytest.raises(ToolError):
        svc.propose_change("browse_url", "bank page", {"url": "https://www.hdfcbank.com/personal"})


def test_browse_open_window_auto_approves() -> None:
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 104

    svc = _svc(".")
    svc.db = FakeSession()
    svc._fetch_browse = lambda _u: "the page text"  # type: ignore[method-assign]

    class FakeSettings:
        self_edit_roots = "."
        mira_self_write_roots = "data/self"
        mira_self_write_deny = ""
        mira_self_write_autonomous = False
        browse_window_open = True
        host_window_open = False
        mira_browse_allowed_domains = ""
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()
    change = svc.propose_change("browse_url", "learn", {"url": "https://en.wikipedia.org/wiki/Companionship"})
    assert change.status == "approved"
    assert change.result == "the page text"


def test_research_auto_approves_when_autonomous(monkeypatch, tmp_path: pytest.TempPathFactory) -> None:
    """Research is read-only, so with the wall open it runs at once — still fully
    recorded in pending_changes, result attached, no approval popup."""
    svc = _with_settings(tmp_path, research_window_open=True)
    monkeypatch.setattr(
        "app.services.tools.service.ToolService._render_research",
        lambda self, query: "Real papers about DNA replication.",
    )
    change = svc.propose_change(
        "research_query",
        "she wants the literature",
        {"query": "DNA replication"},
    )
    assert change.status == "approved"
    assert change.result == "Real papers about DNA replication."
    assert change.kind == "research_query"


def test_render_research_keeps_many_papers_with_protocol(monkeypatch, tmp_path: pytest.TempPathFactory) -> None:
    """One search returns up to twenty real papers, deduplicated by DOI, with a
    search-protocol header — enough of the record for a real review, and not
    truncated down to a handful."""
    import app.services.tools.service as tools_module

    hits = []
    for i in range(20):
        hits.append(
            {
                "title": f"Paper number {i} on DNA replication",
                "authorString": f"Author {i}, Collaborator A",
                "journalTitle": f"Journal of Replication {i}",
                "pubYear": 2020 + (i % 5),
                "citedByCount": i * 3,
                "doi": f"10.1000/paper{i}",
                "pmcid": f"PMC{i:07d}",
                "abstractText": f"Abstract {i}. " * 40,
            }
        )
    # a duplicate DOI that must be dropped by dedup
    hits.append({**hits[0], "pmcid": "PMC9999999"})

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"resultList": {"result": hits}}

    def fake_get(url, params, timeout, headers, follow_redirects):
        assert url == "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        assert params["pageSize"] == 20
        return _Resp()

    monkeypatch.setattr(tools_module.httpx, "get", fake_get)

    svc = _svc(str(tmp_path))
    out = svc._render_research("DNA replication")
    assert "Search protocol:" in out
    assert "returned = 20" in out
    assert "kept = 20" in out
    assert "1. Paper number 0" in out
    assert "20. Paper number 19" in out
    assert "PMC9999999" not in out
    assert "(truncated)" not in out


def test_research_stays_pending_when_wall_closed(tmp_path: pytest.TempPathFactory) -> None:
    """With the research wall closed, a proposed search stays pending for the
    user's approval — the old, explicit path."""
    added: list = []

    class FakeSession:
        def add(self, obj) -> None:
            added.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 105

    svc = _with_settings(tmp_path, research_window_open=False)
    svc.db = FakeSession()
    change = svc.propose_change(
        "research_query",
        "she wants the literature",
        {"query": "DNA replication"},
    )
    assert change.status == "pending"
    assert change.result is None
    assert added[0].status == "pending"


def test_wikipedia_browse_uses_clean_extract(monkeypatch, tmp_path) -> None:
    """Wikipedia pages go through the REST API extract, which skips the nav
    boilerplate that makes the first ~2400 chars of scraped HTML unreadable."""
    svc = _svc(str(tmp_path))

    class FakeSettings:
        self_edit_roots = "."
        browse_window_open = True
        host_window_open = False
        mira_browse_allowed_domains = ""
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()

    def fake_wikipedia(url: str) -> str:
        assert "wikipedia.org" in url
        return "Kyoto is a city in the Kansai region of Japan. Clean lead text."

    svc._fetch_wikipedia_page = fake_wikipedia  # type: ignore[method-assign]
    result = svc._fetch_browse("https://en.wikipedia.org/wiki/Kyoto")
    assert result.startswith("Kyoto is a city")
    assert "Jump to content" not in result


def test_wikipedia_extract_falls_back_to_html(monkeypatch, tmp_path) -> None:
    """If the REST extract is unavailable, browsing degrades to the scraped
    text instead of failing."""
    svc = _svc(str(tmp_path))
    svc._fetch_wikipedia_page = lambda _url: ""  # type: ignore[method-assign]

    class FakeSettings:
        self_edit_roots = "."
        browse_window_open = True
        host_window_open = False
        mira_browse_allowed_domains = ""
        mira_money_deny_domains = ""
        mira_money_deny_commands = ""
        mira_archive_path = ""

    import app.services.tools.service as tools_module

    tools_module.get_settings = lambda: FakeSettings()

    def fake_stream(_client, method, url):  # noqa: ANN001, ANN202
        raise RuntimeError("network off")

    monkeypatch.setattr("app.services.tools.service.httpx.Client", fake_stream)
    result = svc._fetch_browse("https://en.wikipedia.org/wiki/Kyoto")
    assert result.startswith("[error]")


def test_approve_rejects_money_command_defense_in_depth(tmp_path) -> None:
    """Even a money command that somehow reached pending state cannot be
    approved — the wall is re-checked at approval time."""
    from types import SimpleNamespace

    change = SimpleNamespace(
        id=200,
        kind="host_command",
        status="pending",
        payload={"command": "Get-ChildItem ~/upstox-dashboard"},
        result=None,
        resolved_at=None,
    )

    class FakeSession:
        def commit(self) -> None:
            pass

        def refresh(self, _obj) -> None:
            pass

        def get(self, _model, cid):
            assert cid == 200
            return change

    svc = _with_settings(tmp_path, mira_money_deny_commands="upi, transfer, upstox, buy, sell, pay")
    svc.db = FakeSession()
    with pytest.raises(ToolError):
        svc.approve(200)


def test_approve_rejects_money_domain_defense_in_depth(tmp_path) -> None:
    """Approval of a browse to a money domain is refused too, even if the change
    was proposed before the wall existed."""
    from types import SimpleNamespace

    change = SimpleNamespace(
        id=201,
        kind="browse_url",
        status="pending",
        payload={"url": "https://www.wellsfargo.com/sign-in"},
        result=None,
        resolved_at=None,
    )

    class FakeSession:
        def commit(self) -> None:
            pass

        def refresh(self, _obj) -> None:
            pass

        def get(self, _model, cid):
            assert cid == 201
            return change

    svc = _with_settings(
        tmp_path,
        mira_money_deny_domains="paypal.com, wellsfargo.com, hdfcbank.com",
    )
    svc.db = FakeSession()
    with pytest.raises(ToolError):
        svc.approve(201)

