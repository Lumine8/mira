from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Conversation, Message, PendingChange, Reminder, User
from app.services.reminders.service import ReminderLoop, ReminderService, _fire_line, parse_when


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Reminder.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    PendingChange.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def sessionmaker_factory():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Reminder.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    PendingChange.__table__.create(engine)
    return sessionmaker(bind=engine)


def _user_id(db) -> int:
    user = User(name="someone", role="person")
    db.add(user)
    db.commit()
    return user.id


# -- parse_when -----------------------------------------------------------

def test_parse_when_iso() -> None:
    assert parse_when("2026-08-19T17:30") == datetime(2026, 8, 19, 17, 30, tzinfo=UTC)


def test_parse_when_iso_with_spaces() -> None:
    assert parse_when("2026-08-19 17:30") == datetime(2026, 8, 19, 17, 30, tzinfo=UTC)


def test_parse_when_in_minutes() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("in 30 minutes", now=now) == now + timedelta(minutes=30)


def test_parse_when_in_hours() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("in 2 hours", now=now) == now + timedelta(hours=2)


def test_parse_when_in_days() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("in 3 days", now=now) == now + timedelta(days=3)


def test_parse_when_clock_pm() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("at 5pm", now=now) == datetime(2026, 8, 19, 17, 0, tzinfo=UTC)


def test_parse_when_clock_am_future() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("9am", now=now) == datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def test_parse_when_tomorrow() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("tomorrow at 9am", now=now) == datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def test_parse_when_today_past_clock_rolls_forward() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert parse_when("at 9am", now=now) == datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def test_parse_when_garbage_is_none() -> None:
    assert parse_when("whenever") is None
    assert parse_when("") is None
    assert parse_when("sometime soon") is None


# -- service --------------------------------------------------------------

def test_create_and_list(db) -> None:
    user_id = _user_id(db)
    svc = ReminderService(db, user_id=user_id)
    due = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    svc.create(title="call the dentist", due_at=due)
    svc.create(title="water the plants", kind="task")
    rows = svc.list()
    assert [r.title for r in rows] == ["call the dentist", "water the plants"]


def test_list_excludes_done(db) -> None:
    user_id = _user_id(db)
    svc = ReminderService(db, user_id=user_id)
    item = svc.create(title="buy milk", due_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC))
    svc.mark_done(item.id)
    assert svc.list() == []
    assert len(svc.list(include_done=True)) == 1


def test_delete(db) -> None:
    user_id = _user_id(db)
    svc = ReminderService(db, user_id=user_id)
    item = svc.create(title="buy milk")
    assert svc.delete(item.id) is True
    assert svc.delete(item.id) is False
    assert svc.list() == []


def test_unknown_kind_falls_back_to_reminder(db) -> None:
    user_id = _user_id(db)
    svc = ReminderService(db, user_id=user_id)
    item = svc.create(title="weird", kind="alarm-clock")
    assert item.kind == "reminder"


# -- fire line ------------------------------------------------------------

def test_fire_line_reminder_phrase() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    item = Reminder(kind="reminder", title="call mom", due_at=now + timedelta(hours=2))
    line = _fire_line(item, now)
    assert line.startswith("Reminder: call mom")
    assert "in 2 hours" in line


def test_fire_line_event() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    item = Reminder(kind="event", title="dentist appointment", due_at=now + timedelta(days=1))
    line = _fire_line(item, now)
    assert "dentist appointment" in line
    assert "in 1 days" in line


def test_fire_line_open_task_has_no_when() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    item = Reminder(kind="task", title="finish the essay", due_at=None)
    assert _fire_line(item, now) == "finish the essay"


# -- loop -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_fires_due_reminder(sessionmaker_factory, monkeypatch) -> None:
    db = sessionmaker_factory()
    try:
        user_id = _user_id(db)
        conv = Conversation(kind="self", user_id=user_id)
        db.add(conv)
        db.commit()

        due = datetime.now(UTC) - timedelta(seconds=5)
        svc = ReminderService(db, user_id=user_id)
        item = svc.create(title="take the pill", due_at=due)
        item_id = item.id
    finally:
        db.close()

    sent: list[dict] = []

    async def fake_broadcast(payload: dict, **kwargs):
        sent.append(payload)

    monkeypatch.setattr("app.services.reminders.service.live_hub.broadcast", fake_broadcast)
    monkeypatch.setattr("app.services.reminders.service.SessionLocal", sessionmaker_factory)
    monkeypatch.setattr("app.services.reminders.service.founder_user_id", lambda _db: user_id)

    loop = ReminderLoop()
    await loop.tick()

    assert len(sent) == 1
    assert sent[0]["type"] == "self_message"
    assert "take the pill" in sent[0]["content"]

    # Second tick must not fire again.
    await loop.tick()
    assert len(sent) == 1

    check = sessionmaker_factory()
    try:
        row = check.get(Reminder, item_id)
        assert row.notified is True
        assert row.done is True  # one-shot: spoken once, then done
    finally:
        check.close()


@pytest.mark.asyncio
async def test_loop_does_not_fire_future_or_done(sessionmaker_factory, monkeypatch) -> None:
    db = sessionmaker_factory()
    try:
        user_id = _user_id(db)
        db.add(Conversation(kind="self", user_id=user_id))
        db.commit()

        svc = ReminderService(db, user_id=user_id)
        svc.create(title="future thing", due_at=datetime.now(UTC) + timedelta(hours=1))
        past = svc.create(title="already done", due_at=datetime.now(UTC) - timedelta(seconds=5))
        svc.mark_done(past.id)
    finally:
        db.close()

    sent: list[dict] = []

    async def fake_broadcast(payload: dict, **kwargs):
        sent.append(payload)

    monkeypatch.setattr("app.services.reminders.service.live_hub.broadcast", fake_broadcast)
    monkeypatch.setattr("app.services.reminders.service.SessionLocal", sessionmaker_factory)
    monkeypatch.setattr("app.services.reminders.service.founder_user_id", lambda _db: user_id)

    await ReminderLoop().tick()
    assert sent == []


@pytest.mark.asyncio
async def test_loop_fires_open_task_as_done(sessionmaker_factory, monkeypatch) -> None:
    db = sessionmaker_factory()
    try:
        user_id = _user_id(db)
        db.add(Conversation(kind="self", user_id=user_id))
        db.commit()

        svc = ReminderService(db, user_id=user_id)
        item = svc.create(title="no due moment task", kind="task", due_at=None)
        item_id = item.id
    finally:
        db.close()

    sent: list[dict] = []

    async def fake_broadcast(payload: dict, **kwargs):
        sent.append(payload)

    monkeypatch.setattr("app.services.reminders.service.live_hub.broadcast", fake_broadcast)
    monkeypatch.setattr("app.services.reminders.service.SessionLocal", sessionmaker_factory)
    monkeypatch.setattr("app.services.reminders.service.founder_user_id", lambda _db: user_id)

    await ReminderLoop().tick()
    # Open tasks never fire (no due moment).
    assert sent == []

    check = sessionmaker_factory()
    try:
        row = check.get(Reminder, item_id)
        assert row.notified is False
        assert row.done is False
    finally:
        check.close()


# -- tool ----------------------------------------------------------------

class _FakeSettings:
    self_edit_roots = "."
    mira_self_write_roots = "."
    mira_self_write_deny = ""
    mira_self_write_autonomous = False
    browse_window_open = False
    host_window_open = False
    mira_money_deny_domains = ""
    mira_money_deny_commands = ""
    mira_archive_path = ""


def test_remind_tool_validates_and_applies(db, monkeypatch) -> None:
    import app.services.tools.service as tools_module

    monkeypatch.setattr(tools_module, "get_settings", lambda: _FakeSettings())
    user_id = _user_id(db)

    from app.services.tools.service import ToolService

    change = ToolService(db, user_id=user_id).propose_change(
        "remind",
        "she wants to keep it",
        {"title": "call the dentist", "when": "in 2 hours", "reason": "the tooth"},
    )
    assert change.status == "approved"
    assert "call the dentist" in (change.result or "")

    row = db.execute(select(Reminder).where(Reminder.user_id == user_id)).scalar_one()
    assert row.title == "call the dentist"
    assert row.kind == "reminder"
    assert row.note == "the tooth"
    assert row.due_at is not None


def test_remind_tool_rejects_missing_title(db, monkeypatch) -> None:
    import app.services.tools.service as tools_module

    monkeypatch.setattr(tools_module, "get_settings", lambda: _FakeSettings())
    user_id = _user_id(db)

    from app.services.tools.service import ToolError, ToolService

    with pytest.raises(ToolError):
        ToolService(db, user_id=user_id).propose_change(
            "remind", "x", {"title": "  ", "when": "in 2 hours"}
        )


def test_remind_tool_rejects_bad_when(db, monkeypatch) -> None:
    import app.services.tools.service as tools_module

    monkeypatch.setattr(tools_module, "get_settings", lambda: _FakeSettings())
    user_id = _user_id(db)

    from app.services.tools.service import ToolError, ToolService

    with pytest.raises(ToolError):
        ToolService(db, user_id=user_id).propose_change(
            "remind", "x", {"title": "call", "when": "sometime never"}
        )