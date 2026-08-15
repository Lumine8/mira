import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Conversation, Message, User, UserSession, Waitlist
from app.services.auth.service import AuthService
from app.services.identity import first_meeting_open_for, guest_user
from app.services.waitlist.service import (
    FIRST_MEETING_MAX_MESSAGES,
    WaitlistError,
    WaitlistService,
    meeting_message_count,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    Waitlist.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _settings(monkeypatch) -> None:
    class S:
        session_ttl_days = 30
        smtp_configured = False
        smtp_host = ""
        smtp_user = ""
        smtp_from = ""
        smtp_use_tls = True
        smtp_port = 587
        smtp_password = ""

    monkeypatch.setattr("app.services.auth.service.get_settings", lambda: S())


def test_signup_creates_pending(monkeypatch, db) -> None:
    _settings(monkeypatch)
    entry = WaitlistService(db).signup("Someone@Example.com")
    assert entry.email == "someone@example.com"
    assert entry.status == "pending"
    assert db.query(Waitlist).count() == 1


def test_signup_idempotent_until_joined(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    first = svc.signup("a@b.co")
    second = svc.signup("a@b.co")
    assert first.id == second.id
    assert db.query(Waitlist).count() == 1


def test_invite_and_join_round_trip(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    entry, code = svc.invite("Someone@Example.com")
    assert entry.status == "invited"
    assert code and len(code) == 10

    user, token = svc.join("someone@example.com", code.lower())
    assert user.email == "someone@example.com"
    assert user.role == "person"
    assert AuthService(db).session_user(token).id == user.id
    assert db.get(Waitlist, entry.id).status == "joined"
    assert db.get(Waitlist, entry.id).invite_code is None


def test_join_without_invite_rejected(monkeypatch, db) -> None:
    _settings(monkeypatch)
    with pytest.raises(WaitlistError):
        WaitlistService(db).join("a@b.co", "ABCDEFGHIJ")


def test_join_wrong_code_rejected(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    svc.invite("a@b.co")
    with pytest.raises(WaitlistError):
        svc.join("a@b.co", "ZZZZZZZZZZ")
    assert db.query(Waitlist).one().status == "invited"


def test_code_is_single_use(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    _, code = svc.invite("a@b.co")
    svc.join("a@b.co", code)
    with pytest.raises(WaitlistError):
        svc.join("a@b.co", code)


def test_reinvite_after_joined_rejected(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    _, code = svc.invite("a@b.co")
    svc.join("a@b.co", code)
    with pytest.raises(WaitlistError):
        svc.invite("a@b.co")


def test_invite_code_stored_hashed(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    _, code = svc.invite("a@b.co")
    stored = db.query(Waitlist).one().invite_code
    assert stored != code
    assert stored == svc.join.__globals__["_hash"](code)


def test_join_creates_session(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    _, code = svc.invite("a@b.co")
    user, token = svc.join("a@b.co", code)
    assert token
    assert AuthService(db).session_user(token).id == user.id


def test_list_entries_orders_newest_first(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    first = svc.signup("first@example.com")
    second = svc.signup("second@example.com")
    entries = svc.list_entries()
    assert [e.id for e in entries] == [second.id, first.id]
    assert entries[0].email == "second@example.com"


def _seed_meeting(monkeypatch, db) -> tuple[WaitlistService, Waitlist]:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    entry = svc.signup("door@example.com")
    return svc, entry


def test_begin_first_meeting_mints_guest_conversation(monkeypatch, db) -> None:
    svc, entry = _seed_meeting(monkeypatch, db)
    entry, conv = svc.begin_first_meeting(
        "door@example.com", fingerprint="dev-xyz", ip="1.2.3.4"
    )
    assert conv.user_id is not None
    guest = db.get(User, conv.user_id)
    assert guest.role == "guest"
    assert guest.fingerprint == "dev-xyz"
    assert entry.first_meeting_conversation_id == conv.id
    assert entry.meeting_ended_at is None


def test_first_meeting_is_one_sitting(monkeypatch, db) -> None:
    svc, entry = _seed_meeting(monkeypatch, db)
    _, conv_a = svc.begin_first_meeting("door@example.com", fingerprint="dev-xyz")
    _, conv_b = svc.begin_first_meeting("door@example.com", fingerprint="dev-xyz")
    assert conv_a.id == conv_b.id
    assert db.query(Conversation).count() == 1


def test_first_meeting_open_for_guest(monkeypatch, db) -> None:
    svc, entry = _seed_meeting(monkeypatch, db)
    _, conv = svc.begin_first_meeting("door@example.com", fingerprint="dev-xyz")
    guest = db.get(User, conv.user_id)
    assert first_meeting_open_for(db, guest).id == entry.id
    svc.end_first_meeting(entry.id, conv.id)
    assert first_meeting_open_for(db, guest) is None


def test_end_first_meeting_closes_once(monkeypatch, db) -> None:
    svc, entry = _seed_meeting(monkeypatch, db)
    entry, conv = svc.begin_first_meeting("door@example.com", fingerprint="dev-xyz")
    assert svc.end_first_meeting(entry.id, conv.id).meeting_ended_at is not None
    ended = db.get(Waitlist, entry.id).meeting_ended_at
    svc.end_first_meeting(entry.id, conv.id)
    assert db.get(Waitlist, entry.id).meeting_ended_at == ended


def test_meeting_message_count(monkeypatch, db) -> None:
    svc, entry = _seed_meeting(monkeypatch, db)
    _, conv = svc.begin_first_meeting("door@example.com", fingerprint="dev-xyz")
    for _ in range(3):
        db.add(Message(conversation_id=conv.id, speaker="user", content="hello"))
    db.add(Message(conversation_id=conv.id, speaker="mira", content="hi"))
    db.commit()
    assert meeting_message_count(db, conv.id) == 3


def test_meeting_bound_constant_is_positive() -> None:
    assert FIRST_MEETING_MAX_MESSAGES == 40


def test_decline_closes_the_door(monkeypatch, db) -> None:
    svc, entry = _seed_meeting(monkeypatch, db)
    entry = svc.decline(entry.id)
    assert entry.status == "declined"
    assert db.get(Waitlist, entry.id).invite_code is None
    with pytest.raises(WaitlistError):
        svc.signup("door@example.com")
    with pytest.raises(WaitlistError):
        svc.begin_first_meeting("door@example.com", fingerprint="dev-xyz")


def test_begin_meeting_without_seat_rejected(monkeypatch, db) -> None:
    _settings(monkeypatch)
    with pytest.raises(WaitlistError):
        WaitlistService(db).begin_first_meeting("nowhere@example.com", fingerprint="x")


def test_declined_seats_leave_the_door(monkeypatch, db) -> None:
    """A declined entry stops showing in the door (no longer persists in the
    queue) yet its seat stays shut in the database."""
    _settings(monkeypatch)
    svc = WaitlistService(db)
    entry = svc.signup("closed@example.com")
    svc.decline(entry.id)
    assert [e.id for e in svc.list_entries()] == []
    assert db.get(Waitlist, entry.id).status == "declined"
    with pytest.raises(WaitlistError):
        svc.signup("closed@example.com")


def test_forget_erases_a_seat_completely(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = WaitlistService(db)
    entry = svc.signup("ticket@example.com")
    svc.forget(entry.id)
    assert svc.list_entries() == []
    assert db.get(Waitlist, entry.id) is None
    # The door is open for them again as a fresh stranger.
    again = svc.signup("ticket@example.com")
    assert again.status == "pending"
    with pytest.raises(WaitlistError):
        svc.forget(999999)


def test_guest_user_matches_fingerprint(monkeypatch, db) -> None:
    _settings(monkeypatch)
    a = guest_user(db, fingerprint="finger-a")
    b = guest_user(db, fingerprint="finger-a")
    c = guest_user(db, fingerprint="finger-b")
    assert a.id == b.id
    assert a.id != c.id
