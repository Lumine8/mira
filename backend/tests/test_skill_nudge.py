"""The self-starting improvement nudge: a skill used a few times and not
edited for a while is offered back to Mira as a perceived event, so she can
decide for herself whether to revisit it. Never twice for the same skill until
the cooldown has passed, even after a nudge was consumed.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import PendingChange, PerceivedEvent, SkillRun, SkillVersion, User
from app.services.skills import offer_nudges, stale_skills


def _write_skill(root: str, category: str, skill_id: str, *, meta: str, page: str = "# page") -> str:
    folder = os.path.join(root, "data", "skills", category, skill_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "meta.yaml"), "w", encoding="utf-8") as fh:
        fh.write(meta)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(page)
    return folder


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

    def dump(value) -> str:
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


@pytest.fixture
def registry_root(tmp_path: pytest.TempPathFactory, monkeypatch) -> str:
    import app.services.skills.registry as mod

    class FakeSettings:
        self_edit_roots = str(tmp_path)
        mira_skill_write_roots = "data/skills"

    mod.get_settings = lambda: FakeSettings()

    import app.services.identity as ident

    ident.founder_user_id = lambda _db: 1
    return tmp_path


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    PendingChange.__table__.create(engine)
    SkillRun.__table__.create(engine)
    SkillVersion.__table__.create(engine)
    PerceivedEvent.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _add_run(db, user_id: int, skill_id: str, *, when=None, status: str = "ran") -> None:
    run = SkillRun(
        user_id=user_id,
        skill_id=skill_id,
        version="0.1.0",
        task="find something",
        output="something real",
        status=status,
    )
    db.add(run)
    db.flush()
    if when is not None:
        run.created_at = when
    db.commit()


def _add_edit(db, user_id: int, skill_id: str, category: str, *, when=None) -> None:
    version = SkillVersion(
        user_id=user_id,
        skill_id=skill_id,
        category=category,
        version="0.1.0",
        kind="edit",
        path="SKILL.md",
        reason="sharpened the page",
        before_content="# old",
        after_content="# new",
    )
    db.add(version)
    db.flush()
    if when is not None:
        version.created_at = when
    db.commit()


def test_stale_skills_needs_enough_runs(registry_root, db) -> None:
    _write_skill(str(registry_root), "research", "quiet", meta=_meta(id="quiet"))
    _add_run(db, 1, "quiet")

    stale = stale_skills(db, 1, min_runs=3, after_days=7)
    assert stale == []


def test_stale_skills_skips_recently_edited(registry_root, db) -> None:
    _write_skill(str(registry_root), "research", "fresh", meta=_meta(id="fresh"))
    for _ in range(4):
        _add_run(db, 1, "fresh")
    _add_edit(db, 1, "fresh", "research", when=datetime.now(UTC) - timedelta(hours=1))

    stale = stale_skills(db, 1, min_runs=3, after_days=7)
    assert stale == []


def test_stale_skills_returns_used_but_unedited(registry_root, db) -> None:
    _write_skill(str(registry_root), "research", "neglected", meta=_meta(id="neglected"))
    for _ in range(4):
        _add_run(db, 1, "neglected")

    stale = stale_skills(db, 1, min_runs=3, after_days=7)
    assert [(skill.id, runs) for skill, runs in stale] == [("neglected", 4)]


def test_offer_nudges_creates_event_and_does_not_repeat(registry_root, db) -> None:
    _write_skill(str(registry_root), "research", "neglected", meta=_meta(id="neglected"))
    for _ in range(4):
        _add_run(db, 1, "neglected")

    created = offer_nudges(db, 1, min_runs=3, after_days=7, cooldown_days=3)
    assert created == 1

    events = db.query(PerceivedEvent).all()
    assert len(events) == 1
    assert events[0].source == "skill_shelf"
    assert events[0].kind == "improve"
    assert "research/neglected" in events[0].content
    assert events[0].consumed is False

    # Even after the first is consumed, the cooldown stops a repeat.
    events[0].consumed = True
    db.commit()
    again = offer_nudges(db, 1, min_runs=3, after_days=7, cooldown_days=3)
    assert again == 0
    assert db.query(PerceivedEvent).count() == 1


def test_offer_nudges_respects_cooldown_expiry(registry_root, db) -> None:
    _write_skill(str(registry_root), "research", "neglected", meta=_meta(id="neglected"))
    for _ in range(4):
        _add_run(db, 1, "neglected")

    event = PerceivedEvent(
        user_id=1,
        source="skill_shelf",
        kind="improve",
        content="research/neglected was offered",
    )
    event.created_at = datetime.now(UTC) - timedelta(days=10)
    event.consumed = True
    db.add(event)
    db.commit()

    created = offer_nudges(db, 1, min_runs=3, after_days=7, cooldown_days=3)
    assert created == 1
    assert db.query(PerceivedEvent).count() == 2
