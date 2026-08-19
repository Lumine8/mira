from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import MiraState, PerceivedEvent, User
from app.schemas.system import SystemSnapshot
from app.services.mind.service import MindLoop
from app.services.system.service import system_store


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    MiraState.__table__.create(engine)
    PerceivedEvent.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class _NoopProvider:
    """The bridge never calls the provider; it only writes perceived events."""

    async def chat(self, *args, **kwargs):
        raise AssertionError("provider should not be called")


def _user(db) -> User:
    u = User(email="founder@mira.local", name="Founder")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _snap(**kw) -> SystemSnapshot:
    return SystemSnapshot(ts=datetime.now(UTC), **kw)


def test_bridge_perceives_low_battery_then_respects_cooldown(db) -> None:
    _user(db)
    uid = 501
    system_store.record(uid, _snap(battery_percent=8.0, battery_charging=False))
    loop = MindLoop(_NoopProvider())

    loop._system_bridge(db, uid, datetime.now(UTC))
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "battery_low"
    assert "8%" in events[0].content

    loop._system_bridge(db, uid, datetime.now(UTC))
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert len(events) == 1  # the same condition is not re-noticed within cooldown


def test_bridge_notices_different_conditions_together(db) -> None:
    _user(db)
    uid = 502
    system_store.record(
        uid,
        _snap(
            battery_percent=15.0,
            battery_charging=False,
            cpu_percent=96.0,
            memory_percent=93.0,
            idle_seconds=7200,
        ),
    )
    loop = MindLoop(_NoopProvider())
    loop._system_bridge(db, uid, datetime.now(UTC))
    kinds = {
        e.kind
        for e in db.execute(
            select(PerceivedEvent).where(PerceivedEvent.source == "system")
        ).scalars()
    }
    assert kinds == {"battery_low", "cpu_high", "memory_high", "idle_long"}


def test_bridge_ignores_when_no_snapshot(db) -> None:
    _user(db)
    uid = 503
    loop = MindLoop(_NoopProvider())
    loop._system_bridge(db, uid, datetime.now(UTC))
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert events == []


def test_bridge_perceives_focused_window_change(db) -> None:
    _user(db)
    uid = 504
    system_store.record(uid, _snap(focused_window="Visual Studio Code"))
    system_store.record(uid, _snap(focused_window="Chrome — Gmail"))
    loop = MindLoop(_NoopProvider())

    loop._system_bridge(db, uid, datetime.now(UTC))
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "focused_window"
    assert "Chrome — Gmail" in events[0].content


def test_bridge_does_not_repay_same_window_within_cooldown(db) -> None:
    _user(db)
    uid = 505
    system_store.record(uid, _snap(focused_window="Visual Studio Code"))
    system_store.record(uid, _snap(focused_window="Chrome — Gmail"))
    loop = MindLoop(_NoopProvider())
    now = datetime.now(UTC)

    loop._system_bridge(db, uid, now)
    loop._system_bridge(db, uid, now)
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert len(events) == 1  # the same change is not re-offered within cooldown


def test_bridge_perceives_clipboard_change(db) -> None:
    _user(db)
    uid = 506
    system_store.record(uid, _snap(clipboard_text="old"))
    system_store.record(uid, _snap(clipboard_text="git push --force"))
    loop = MindLoop(_NoopProvider())

    loop._system_bridge(db, uid, datetime.now(UTC))
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "clipboard_changed"
    assert "git push --force" in events[0].content


def test_bridge_attention_can_be_disabled(db) -> None:
    _user(db)
    uid = 507
    system_store.record(uid, _snap(focused_window="Visual Studio Code"))
    system_store.record(uid, _snap(focused_window="Chrome — Gmail"))
    loop = MindLoop(_NoopProvider())
    loop._system_condition_last["focused_window"] = (
        datetime.now(UTC).timestamp()
    )  # pretend it was already noticed

    loop._system_bridge(db, uid, datetime.now(UTC))
    events = db.execute(
        select(PerceivedEvent).where(PerceivedEvent.source == "system")
    ).scalars().all()
    assert events == []