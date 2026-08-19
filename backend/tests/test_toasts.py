from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Conversation, HostToast, Message, Reminder, User
from app.services.reminders.service import ReminderLoop, ReminderService
from app.services.toasts.service import enqueue_host_toast


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    HostToast.__table__.create(engine)
    Reminder.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def sessionmaker_factory():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    HostToast.__table__.create(engine)
    Reminder.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    return sessionmaker(bind=engine)


def _user_id(db) -> int:
    user = User(name="someone", role="person")
    db.add(user)
    db.commit()
    return user.id


# -- enqueue_host_toast -----------------------------------------------------

def test_enqueue_creates_undelivered_row(db) -> None:
    uid = _user_id(db)
    enqueue_host_toast(db, uid, "hi from Mira", source="self")
    rows = db.execute(select(HostToast).where(HostToast.user_id == uid)).scalars().all()
    assert len(rows) == 1
    assert rows[0].content == "hi from Mira"
    assert rows[0].source == "self"
    assert rows[0].delivered is False


def test_enqueue_respects_custom_title(db) -> None:
    uid = _user_id(db)
    enqueue_host_toast(db, uid, "water the plants", source="reminder", title="Reminder")
    row = db.execute(select(HostToast)).scalar_one()
    assert row.title == "Reminder"
    assert row.source == "reminder"


def test_enqueue_tracks_delivery(db) -> None:
    uid = _user_id(db)
    enqueue_host_toast(db, uid, "ping")
    row = db.execute(select(HostToast)).scalar_one()
    row.delivered = True
    row.delivered_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    assert row.delivered is True
    assert row.delivered_at is not None


def test_enqueue_multiple_orders_oldest_first(db) -> None:
    uid = _user_id(db)
    enqueue_host_toast(db, uid, "first")
    enqueue_host_toast(db, uid, "second")
    rows = db.execute(
        select(HostToast).order_by(HostToast.id.asc())
    ).scalars().all()
    assert [r.content for r in rows] == ["first", "second"]


# -- the reminders loop queues a toast when it fires -------------------------

@pytest.mark.asyncio
async def test_reminder_fire_enqueues_host_toast(sessionmaker_factory, monkeypatch) -> None:
    db = sessionmaker_factory()
    try:
        user_id = _user_id(db)
        conv = Conversation(kind="self", user_id=user_id)
        db.add(conv)
        db.commit()
        due = datetime.now(UTC) - timedelta(seconds=5)
        ReminderService(db, user_id=user_id).create(title="take the bins out", due_at=due)
    finally:
        db.close()

    async def fake_broadcast(payload: dict, **kwargs):
        pass

    monkeypatch.setattr("app.services.reminders.service.live_hub.broadcast", fake_broadcast)
    monkeypatch.setattr("app.services.reminders.service.SessionLocal", sessionmaker_factory)
    monkeypatch.setattr("app.services.reminders.service.founder_user_id", lambda _db: user_id)

    await ReminderLoop().tick()

    check = sessionmaker_factory()
    try:
        toasts = check.execute(
            select(HostToast).where(HostToast.user_id == user_id)
        ).scalars().all()
        assert len(toasts) == 1
        assert toasts[0].source == "reminder"
        assert toasts[0].title == "Reminder"
        assert "take the bins out" in toasts[0].content
    finally:
        check.close()


@pytest.mark.asyncio
async def test_reminder_fire_queues_toast_only_once(sessionmaker_factory, monkeypatch) -> None:
    db = sessionmaker_factory()
    try:
        user_id = _user_id(db)
        conv = Conversation(kind="self", user_id=user_id)
        db.add(conv)
        db.commit()
        due = datetime.now(UTC) - timedelta(seconds=5)
        item = ReminderService(db, user_id=user_id).create(title="one-shot", due_at=due)
        item_id = item.id
    finally:
        db.close()

    async def fake_broadcast(payload: dict, **kwargs):
        pass

    monkeypatch.setattr("app.services.reminders.service.live_hub.broadcast", fake_broadcast)
    monkeypatch.setattr("app.services.reminders.service.SessionLocal", sessionmaker_factory)
    monkeypatch.setattr("app.services.reminders.service.founder_user_id", lambda _db: user_id)

    loop = ReminderLoop()
    await loop.tick()
    await loop.tick()

    check = sessionmaker_factory()
    try:
        toasts = check.execute(
            select(HostToast).where(HostToast.user_id == user_id)
        ).scalars().all()
        assert len(toasts) == 1  # the fired reminder queues exactly one toast
        row = check.get(Reminder, item_id)
        assert row.notified is True
        assert row.done is True
    finally:
        check.close()