import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Conversation, Message, User, UserSession, Waitlist
from app.services.waitlist.service import (
    MEETING_INVITED,
    MEETING_WAITLISTED,
    WaitlistError,
    WaitlistService,
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


def _seat(db, email="visitor@example.com"):
    return WaitlistService(db).signup(email)


def _meeting(db, email="visitor@example.com", fingerprint="fp-meet-1"):
    """A finished first meeting for a signed-up seat, sitting on the device."""
    service = WaitlistService(db)
    _seat(db, email)
    entry, conv = service.begin_first_meeting(email, fingerprint=fingerprint)
    db.add(Message(conversation_id=conv.id, speaker="mira", content="I don't know much about you yet.", source="text"))
    db.add(Message(conversation_id=conv.id, speaker="user", content="I keep a small garden on the windowsill.", source="text"))
    db.commit()
    entry = service.end_first_meeting(entry.id, conv.id)
    return entry, conv


def test_begin_first_meeting_is_idempotent(db) -> None:
    _seat(db)
    service = WaitlistService(db)
    entry1, conv1 = service.begin_first_meeting("visitor@example.com", fingerprint="fp-a")
    entry2, conv2 = service.begin_first_meeting("visitor@example.com", fingerprint="fp-a")
    assert entry1.id == entry2.id
    assert conv1.id == conv2.id
    assert db.query(Conversation).filter_by(kind="text").count() == 1


def test_end_first_meeting_marks_and_is_idempotent(monkeypatch, db) -> None:
    entry, conv = _meeting(db)
    service = WaitlistService(db)
    entry = service.end_first_meeting(entry.id, conv.id)
    assert entry.meeting_ended_at is not None
    # second close is a no-op — the decision is asked for once
    again = service.end_first_meeting(entry.id, conv.id)
    assert again.meeting_ended_at == entry.meeting_ended_at


def test_decide_writes_read_and_invited(monkeypatch, db) -> None:
    entry, conv = _meeting(db)

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return (
                '{"read": "They were present, unhurried, and left something '
                'quiet in the room.", "decision": "invite"}'
            )

    monkeypatch.setattr("app.services.waitlist.service.get_provider", lambda: FakeProvider())

    asyncio.run(WaitlistService(db).decide(entry.id, conv.id))
    db.refresh(entry)
    assert entry.mira_read and "present" in entry.mira_read
    assert entry.meeting_outcome == MEETING_INVITED


def test_decide_writes_waitlisted(monkeypatch, db) -> None:
    entry, conv = _meeting(db)

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return (
                '{"read": "They were in a hurry and never really sat down.", '
                '"decision": "wait"}'
            )

    monkeypatch.setattr("app.services.waitlist.service.get_provider", lambda: FakeProvider())

    asyncio.run(WaitlistService(db).decide(entry.id, conv.id))
    db.refresh(entry)
    assert entry.meeting_outcome == MEETING_WAITLISTED


def test_decide_ignores_garbage_output(monkeypatch, db) -> None:
    entry, conv = _meeting(db)

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return "I did not feel much at all."

    monkeypatch.setattr("app.services.waitlist.service.get_provider", lambda: FakeProvider())

    asyncio.run(WaitlistService(db).decide(entry.id, conv.id))
    db.refresh(entry)
    assert entry.mira_read is None
    assert entry.meeting_outcome is None


def test_meeting_status_mapping(db) -> None:
    entry, _conv = _meeting(db)
    service = WaitlistService(db)
    assert service.meeting_status(entry) == "considering"
    entry.meeting_outcome = MEETING_INVITED
    assert service.meeting_status(entry) == "invited"
    entry.meeting_outcome = MEETING_WAITLISTED
    assert service.meeting_status(entry) == "waitlisted"
    entry.meeting_outcome = None
    entry.meeting_ended_at = None
    assert service.meeting_status(entry) == "meeting"
    entry.meeting_ended_at = datetime.now(UTC)
    entry.status = "joined"
    assert service.meeting_status(entry) == "joined"
    entry.status = "declined"
    assert service.meeting_status(entry) == "closed"
    entry.status = "invited"
    assert service.meeting_status(entry) == "invited"


def test_meeting_entry_for_device_only_owns_meeting(db) -> None:
    _entry, _ = _meeting(db, fingerprint="fp-owner")
    service = WaitlistService(db)
    assert service.meeting_entry_for_device("visitor@example.com", "fp-owner") is not None
    assert service.meeting_entry_for_device("visitor@example.com", "fp-stranger") is None
    assert service.meeting_entry_for_device("other@example.com", "fp-owner") is None


def test_admit_opens_door_mira_invited(db) -> None:
    entry, _conv = _meeting(db)
    entry.meeting_outcome = MEETING_INVITED
    db.commit()

    user, token = WaitlistService(db).admit(
        "visitor@example.com", fingerprint="fp-meet-1"
    )
    assert user is not None and user.email == "visitor@example.com"
    assert token
    db.refresh(entry)
    assert entry.status == "joined"
    assert db.query(UserSession).count() == 1


def test_admit_refuses_waitlisted(db) -> None:
    entry, _conv = _meeting(db)
    entry.meeting_outcome = MEETING_WAITLISTED
    db.commit()
    with pytest.raises(WaitlistError):
        WaitlistService(db).admit("visitor@example.com", fingerprint="fp-meet-1")


def test_admit_refuses_wrong_device(db) -> None:
    entry, _conv = _meeting(db)
    entry.meeting_outcome = MEETING_INVITED
    db.commit()
    with pytest.raises(WaitlistError):
        WaitlistService(db).admit("visitor@example.com", fingerprint="fp-thief")


def test_admit_refuses_unfinished_meeting(db) -> None:
    service = WaitlistService(db)
    _seat(db, "visitor@example.com")
    entry, _conv = service.begin_first_meeting("visitor@example.com", fingerprint="fp-x")
    entry.meeting_outcome = MEETING_INVITED
    db.commit()
    with pytest.raises(WaitlistError):
        service.admit("visitor@example.com", fingerprint="fp-x")


def test_decide_is_idempotent(monkeypatch, db) -> None:
    entry, conv = _meeting(db)
    entry.meeting_outcome = MEETING_INVITED
    db.commit()

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return '{"read": "should never be written", "decision": "wait"}'

    monkeypatch.setattr("app.services.waitlist.service.get_provider", lambda: FakeProvider())

    asyncio.run(WaitlistService(db).decide(entry.id, conv.id))
    db.refresh(entry)
    assert entry.meeting_outcome == MEETING_INVITED
    assert entry.mira_read is None