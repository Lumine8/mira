import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Conversation, Message, User, UserSettings
from app.services.usage import UsageService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserSettings.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _settings(monkeypatch, **overrides) -> None:
    class S:
        guest_message_cap_per_day = 20
        free_user_message_cap_per_day = 60

    for attr, value in overrides.items():
        setattr(S, attr, value)
    monkeypatch.setattr("app.services.usage.service.get_settings", lambda: S())


def _user(db, role="person", **kw) -> User:
    user = User(name="t", role=role, **kw)
    db.add(user)
    db.commit()
    return user


def _send(db, user_id: int, n: int) -> None:
    conv = Conversation(user_id=user_id, kind="text")
    db.add(conv)
    db.flush()
    for _ in range(n):
        db.add(Message(conversation_id=conv.id, speaker="user", content="hi"))
    db.commit()


def test_founder_never_capped(db) -> None:
    user = _user(db, role="founder")
    assert UsageService(db).effective_cap(user) is None
    assert UsageService(db).can_send(user) == (True, None, 0)


def test_guest_cap_uses_guest_default(monkeypatch, db) -> None:
    _settings(monkeypatch)
    user = _user(db, role="guest")
    assert UsageService(db).effective_cap(user) == 20


def test_free_user_cap_uses_free_default(monkeypatch, db) -> None:
    _settings(monkeypatch)
    user = _user(db, role="person")
    assert UsageService(db).effective_cap(user) == 60


def test_settings_override_beats_default(monkeypatch, db) -> None:
    _settings(monkeypatch)
    user = _user(db, role="person")
    db.add(UserSettings(user_id=user.id, message_cap_per_day=5))
    db.commit()
    assert UsageService(db).effective_cap(user) == 5


def test_cap_tracks_usage(monkeypatch, db) -> None:
    _settings(monkeypatch)
    user = _user(db, role="guest")
    svc = UsageService(db)
    assert svc.can_send(user) == (True, 20, 0)
    _send(db, user.id, 19)
    assert svc.can_send(user) == (True, 20, 19)
    _send(db, user.id, 1)
    assert svc.can_send(user) == (False, 20, 20)


def test_mira_messages_do_not_count(db) -> None:
    user = _user(db, role="guest")
    _send(db, user.id, 2)
    conv = db.query(Conversation).filter_by(user_id=user.id).one()
    db.add(Message(conversation_id=conv.id, speaker="mira", content="hi there"))
    db.commit()
    assert UsageService(db).messages_today(user.id) == 2


def test_usage_is_per_user(db) -> None:
    user_a = _user(db, role="guest")
    user_b = _user(db, role="guest")
    _send(db, user_a.id, 3)
    assert UsageService(db).messages_today(user_a.id) == 3
    assert UsageService(db).messages_today(user_b.id) == 0
