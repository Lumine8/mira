"""The skill registry and evaluator: discover, load, validate, check, score.

These run against real files (tmp_path) so the whole shelf mechanics are
exercised: metadata is parsed, pages are loaded, unsafe claims are refused, and
a skill's declared checks actually run and move its score.
"""

import os
from types import SimpleNamespace

import pytest

from app.services.skills import (
    SAFE_SKILL_TOOLS,
    Evidence,
    SkillError,
    SkillRegistry,
    run_checks,
    score,
)


class FakeSession:
    pass


def _write_skill(root: str, category: str, skill_id: str, *, meta: str, page: str = "# page") -> str:
    folder = os.path.join(root, "data", "skills", category, skill_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "meta.yaml"), "w", encoding="utf-8") as fh:
        fh.write(meta)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(page)
    return folder


@pytest.fixture
def registry_root(tmp_path: pytest.TempPathFactory, monkeypatch) -> str:
    # Point the registry's root resolution at a temp dir. registry_root reads
    # `self_edit_roots` + `mira_skill_write_roots`; we fake both to stay put.
    import app.services.skills.registry as mod

    class FakeSettings:
        self_edit_roots = str(tmp_path)
        mira_skill_write_roots = "data/skills"

    mod.get_settings = lambda: FakeSettings()

    # founder_user_id must resolve without a real db. Patch identity import
    # used inside registry_root.
    import app.services.identity as ident

    ident.founder_user_id = lambda _db: 1
    return tmp_path


def _meta(**overrides) -> str:
    base = {
        "id": "demo",
        "version": "0.1.0",
        "status": "draft",
        "purpose": "demonstrate the registry",
        "tools": [],
        "verification": [],
        "failure_modes": [],
        "constraints": [],
        "dependencies": [],
    }
    base.update(overrides)

    def dump(value) -> str:  # keep literal strings simple
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return "[" + ", ".join(f'"{v}"' for v in value) + "]"
        raise TypeError(value)

    return "\n".join(f"{k}: {dump(v)}" for k, v in base.items())


def test_discover_returns_skills(registry_root, monkeypatch) -> None:
    _write_skill(str(registry_root), "research", "solid", meta=_meta(id="solid"))
    _write_skill(str(registry_root), "research", "quiet", meta=_meta(id="quiet"))

    reg = SkillRegistry(FakeSession(), user_id=1)
    skills = reg.list_skills()
    assert [s.id for s in skills] == ["quiet", "solid"]


def test_folders_without_meta_are_ignored(registry_root) -> None:
    _write_skill(str(registry_root), "research", "real", meta=_meta())
    stray = os.path.join(str(registry_root), "data", "skills", "research", "notes")
    os.makedirs(stray, exist_ok=True)
    reg = SkillRegistry(FakeSession(), user_id=1)
    assert [s.id for s in reg.list_skills()] == ["real"]


def test_load_parses_metadata_and_page(registry_root) -> None:
    page_text = "# Research\n\nEvidence above certainty."
    _write_skill(
        str(registry_root),
        "research",
        "paper",
        meta=_meta(
            purpose="find the papers people left behind",
            version="1.2.0",
            status="active",
            tools=["research_query"],
            verification=["output is non-empty", "no invented sources"],
            failure_modes=["empty index"],
        ),
        page=page_text,
    )
    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("paper")
    assert skill.version == "1.2.0"
    assert skill.status == "active"
    assert skill.purpose == "find the papers people left behind"
    assert skill.tools == ["research_query"]
    assert skill.verification == ["output is non-empty", "no invented sources"]
    assert skill.failure_modes == ["empty index"]
    assert skill.page == page_text
    assert skill.category == "research"


def test_id_is_validated_before_reading(registry_root) -> None:
    reg = SkillRegistry(FakeSession(), user_id=1)
    for bad in ("../escape", "with-spaces?", "UPPER"):
        with pytest.raises(SkillError):
            reg.load_skill(bad)


def test_active_skill_requires_purpose(registry_root) -> None:
    _write_skill(str(registry_root), "research", "aimless", meta=_meta(status="active", purpose=""))
    with pytest.raises(SkillError):
        SkillRegistry(FakeSession(), user_id=1).load_skill("aimless")


def test_skill_cannot_claim_dangerous_tools(registry_root) -> None:
    _write_skill(str(registry_root), "research", "greedy", meta=_meta(tools=["host_command"]))
    with pytest.raises(SkillError):
        SkillRegistry(FakeSession(), user_id=1).load_skill("greedy")


def test_valid_skill_can_claim_safe_tools(registry_root) -> None:
    _write_skill(
        str(registry_root),
        "research",
        "reader",
        meta=_meta(status="active", purpose="read things", tools=["research_query", "browse_url"]),
    )
    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("reader")
    assert set(skill.tools) <= SAFE_SKILL_TOOLS


def test_bad_yaml_is_refused(registry_root) -> None:
    _write_skill(
        str(registry_root), "research", "broken", meta="id: broken\n: not valid: ["
    )
    with pytest.raises(SkillError):
        SkillRegistry(FakeSession(), user_id=1).load_skill("broken")


def test_wrong_typed_metadata_is_refused(registry_root) -> None:
    _write_skill(
        str(registry_root), "research", "weird", meta=_meta(status=42, tools="not a list")
    )
    with pytest.raises(SkillError):
        SkillRegistry(FakeSession(), user_id=1).load_skill("weird")


# -- the evaluator ---------------------------------------------------------


def test_run_checks_pass_and_fail() -> None:
    from types import SimpleNamespace

    skill = SimpleNamespace(
        verification=[
            "output is non-empty",
            "no invented sources",
            "no such paper",
        ]
    )
    good = run_checks(skill, "These papers are real, from the record.")
    assert good["checks"]["output is non-empty"] is True
    assert good["checks"]["no invented sources"] is True

    bad = run_checks(skill, "")
    assert bad["checks"]["output is non-empty"] is False


def test_declared_check_with_no_rule_counts_as_missing(registry_root) -> None:
    from types import SimpleNamespace

    skill = SimpleNamespace(verification=["imports resolve"])  # no rule exists
    out = run_checks(skill, "anything")
    assert out["checks"]["imports resolve"] == "skipped"
    assert "imports resolve" in out["missing"]


def test_score_reflects_passes_and_evidence() -> None:
    raw = {
        "checks": {"a": True, "b": True, "c": False},
        "missing": [],
        "evidence": [
            {"claim": "c1", "citation": "10.1000/doi"},
            {"claim": "c2", "citation": ""},
        ],
        "errors": [],
    }
    result = score(raw)
    assert result["overall"] > 0.0
    assert result["dimensions"]["correctness"] == pytest.approx(2 / 3, abs=0.01)
    assert result["dimensions"]["verification"] == pytest.approx(2 / 3, abs=0.01)
    assert result["evidence_count"] == 2


def test_evidence_validation_rejects_shaky_fact() -> None:
    ev = Evidence(claim="the sky is green", category="fact", confidence=0.2)
    ok, why = ev.validate()
    assert not ok
    assert "confident" in why


def test_evidence_accepts_resolvable_doi() -> None:
    ev = Evidence(
        claim="type 1 diabetes follows an HLA-DQ8 signal",
        category="fact",
        citation="doi:10.2337/db13-1560",
        confidence=0.9,
    )
    ok, why = ev.validate()
    assert ok, why


# -- the runner -----------------------------------------------------------


def _fake_db():
    """A tiny in-memory fake session that lets rows get an id on refresh and
    be fetched back from a naive store."""
    store: list = []

    class FakeSession:
        def add(self, obj) -> None:
            store.append(obj)

        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = len(store)

    return FakeSession(), store


def test_runner_records_and_evaluates_a_run(registry_root) -> None:
    from app.services.skills import SkillRunner

    _write_skill(
        str(registry_root), "research", "runme",
        meta=_meta(
            status="active",
            purpose="run it",
            tools=["research_query"],
            verification=["output is non-empty", "no invented sources"],
        ),
    )
    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("runme")
    fake, store = _fake_db()
    runner = SkillRunner(fake, user_id=1)

    run = runner.record_run(skill, "find the warmth", "These papers are real, from the record.")
    assert run.status == "ran"
    assert run.skill_id == "runme"

    evaluation = runner.evaluate(skill, run)
    assert evaluation.run_id == run.id
    scores = evaluation.scores
    assert scores["checks"]["output is non-empty"] is True
    assert scores["checks"]["no invented sources"] is True
    assert 0.0 < scores["overall"] <= 1.0
    assert len(store) == 2  # a run row and an evaluation row


def test_runner_marks_failed_runs(registry_root) -> None:
    from app.services.skills import SkillRunner

    _write_skill(
        str(registry_root), "research", "fails",
        meta=_meta(
            status="active",
            purpose="run it",
            tools=["research_query"],
            verification=["output is non-empty"],
        ),
    )
    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("fails")
    fake, _store = _fake_db()
    runner = SkillRunner(fake, user_id=1)

    run = runner.record_run(skill, "find it", "", status="failed", error="[error] could not search: boom")
    assert run.status == "failed"
    assert run.error.startswith("[error]")

    evaluation = runner.evaluate(skill, run)
    assert evaluation.scores["dimensions"]["failure_rate"] == 0.0
    assert evaluation.scores["checks"]["output is non-empty"] is False


def test_record_skill_tool_run_wires_tool_to_skill(registry_root, monkeypatch) -> None:
    """When a research_query approved change is rendered, the tool runtime
    records a run of whichever skill declared that tool."""
    from app.services.tools.service import ToolService

    _write_skill(
        str(registry_root), "research", "research",
        meta=_meta(
            status="active",
            purpose="find papers",
            tools=["research_query"],
            verification=["output is non-empty"],
        ),
    )

    recorded = {"run": None, "evaluation": None}

    class FakeSession:
        def commit(self) -> None:
            pass

        def refresh(self, obj) -> None:
            obj.id = 7

    class FakeRunner:
        def __init__(self, db, *, user_id):
            pass

        def record_run(self, skill, task, output, *, status="ran", error=None):
            recorded["run"] = (skill.id, task, status)
            return SimpleNamespace(id=7, status=status)

        def evaluate(self, skill, run):
            recorded["evaluation"] = skill.id
            return SimpleNamespace(id=8)

    import app.services.tools.service as tools_module
    tools_module.SkillRunner = FakeRunner

    svc = ToolService.__new__(ToolService)
    svc.db = FakeSession()
    svc.user_id = 1
    svc.roots = [str(registry_root)]
    tools_module.get_settings = lambda: SimpleNamespace(
        mira_skill_write_roots="data/skills",
        self_edit_roots=str(registry_root),
    )
    tools_module.founder_user_id = lambda _db: 1

    svc._record_skill_tool_run("research_query", "find the warmth", "real papers here")
    assert recorded["run"] == ("research", "find the warmth", "ran")
    assert recorded["evaluation"] == "research"

    # A tool no skill declared records nothing.
    svc._record_skill_tool_run("browse_url", "look at a page", "some page text")
    assert recorded["run"] == ("research", "find the warmth", "ran")


# -- the self-improvement loop: versions -----------------------------------


class _VersionDb:
    """A fake session that holds rows and lets them be fetched back, so the
    version service can be tested against real files in tmp_path."""

    def __init__(self):
        self._rows: list = []
        self._next = 1

    def add(self, obj) -> None:
        if not getattr(obj, "id", None):
            obj.id = self._next
            self._next += 1
        self._rows.append(obj)

    def commit(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def get(self, model, cid):
        for row in self._rows:
            if isinstance(row, model) and row.id == cid:
                return row
        return None

    def execute(self, stmt):
        from app.models import SkillVersion

        class FakeResult:
            def scalars(self):
                rows = sorted(
                    (r for r in self_db._rows if isinstance(r, SkillVersion)),
                    key=lambda r: (r.created_at or 0, r.id),
                    reverse=True,
                )
                return _ScalarSeq(rows)

        self_db = self
        return FakeResult()


class _ScalarSeq:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


def test_version_records_edit_and_diff(registry_root) -> None:
    from app.services.skills import SkillVersionService

    folder = _write_skill(
        str(registry_root), "research", "grow",
        meta=_meta(
            status="active",
            purpose="grow",
            tools=[],
            verification=["output is non-empty"],
        ),
    )
    page_path = os.path.join(folder, "SKILL.md")
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write("# old\n\nline two\n")

    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("grow")
    db = _VersionDb()
    svc = SkillVersionService(db, user_id=1)

    svc.record(skill, path="SKILL.md", before="# old\n\nline two\n", after="# new\n\nline two\n", reason="sharpened the page")

    versions = svc.list_for("grow", category="research")
    assert len(versions) == 1
    data = svc.as_dict(versions[0], include_diff=True)
    assert data["kind"] == "edit"
    assert data["path"] == "SKILL.md"
    assert data["reason"] == "sharpened the page"
    tags = [d["tag"] for d in data["diff"]]
    assert "removed" in tags and "added" in tags


def test_version_revert_restores_file(registry_root) -> None:
    from app.services.skills import SkillVersionService

    folder = _write_skill(
        str(registry_root), "research", "grow",
        meta=_meta(status="active", purpose="grow", tools=[], verification=["output is non-empty"]),
    )
    page_path = os.path.join(folder, "SKILL.md")

    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("grow")
    db = _VersionDb()
    svc = SkillVersionService(db, user_id=1)
    version = svc.record(skill, path="SKILL.md", before="# before\n", after="# after\n", reason="try a change")

    # Simulate the write having happened: the file on disk is the "after" state.
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write("# after\n")
    with open(page_path, encoding="utf-8") as fh:
        assert fh.read() == "# after\n"

    reverted = svc.revert(skill, version, registry=SkillRegistry(FakeSession(), user_id=1))
    assert reverted.kind == "revert"
    with open(page_path, encoding="utf-8") as fh:
        assert fh.read() == "# before\n"


def test_version_revert_refuses_to_delete_created_file(registry_root) -> None:
    from app.services.skills import SkillVersionError, SkillVersionService

    _write_skill(
        str(registry_root), "research", "grow",
        meta=_meta(status="active", purpose="grow", tools=[], verification=["output is non-empty"]),
    )
    skill = SkillRegistry(FakeSession(), user_id=1).load_skill("grow")
    db = _VersionDb()
    svc = SkillVersionService(db, user_id=1)
    version = svc.record(skill, path="notes.md", before=None, after="brand new", reason="added a note")

    try:
        svc.revert(skill, version, registry=SkillRegistry(FakeSession(), user_id=1))
        raise AssertionError("reverting a created file should be refused")
    except SkillVersionError:
        pass


def test_apply_write_records_a_version_when_inside_registry(registry_root, monkeypatch) -> None:
    """A skill-root write through the tool runtime pins a version automatically."""
    from app.services.tools.service import ToolService

    folder = _write_skill(
        str(registry_root), "research", "grow",
        meta=_meta(status="active", purpose="grow", tools=[], verification=["output is non-empty"]),
    )
    page_path = os.path.join(folder, "SKILL.md")
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write("# old\n")

    db = _VersionDb()
    svc = ToolService.__new__(ToolService)
    svc.db = db
    svc.user_id = 1
    svc.roots = [str(registry_root)]

    import app.services.tools.service as tools_module
    tools_module.get_settings = lambda: SimpleNamespace(
        mira_self_write_roots="",
        mira_self_write_deny="",
        mira_skill_write_roots="data/skills",
        self_edit_roots=str(registry_root),
    )
    tools_module.founder_user_id = lambda _db: 1

    change = SimpleNamespace(id=42, summary="sharpen the page")
    svc._apply_write({"path": "data/skills/research/grow/SKILL.md", "content": "# new\n"}, change=change)

    from app.models import SkillVersion

    versions = [r for r in db._rows if isinstance(r, SkillVersion)]
    assert len(versions) == 1
    assert versions[0].path == "SKILL.md"
    assert versions[0].before_content == "# old\n"
    assert versions[0].after_content == "# new\n"
    assert versions[0].change_id == 42
    with open(page_path, encoding="utf-8") as fh:
        assert fh.read() == "# new\n"


def test_apply_write_outside_registry_records_nothing(registry_root, monkeypatch) -> None:
    from app.services.tools.service import ToolService

    (registry_root / "data" / "self").mkdir(parents=True)
    (registry_root / "data" / "self" / "principles.md").write_text("stay curious", encoding="utf-8")

    db = _VersionDb()
    svc = ToolService.__new__(ToolService)
    svc.db = db
    svc.user_id = 1
    svc.roots = [str(registry_root)]

    import app.services.tools.service as tools_module
    tools_module.get_settings = lambda: SimpleNamespace(
        mira_self_write_roots="data/self",
        mira_self_write_deny="",
        mira_skill_write_roots="data/skills",
        self_edit_roots=str(registry_root),
    )
    tools_module.founder_user_id = lambda _db: 1

    change = SimpleNamespace(id=43, summary="tweak my principles")
    svc._apply_write({"path": "data/self/principles.md", "content": "stay even more curious\n"}, change=change)

    from app.models import SkillVersion

    assert not [r for r in db._rows if isinstance(r, SkillVersion)]