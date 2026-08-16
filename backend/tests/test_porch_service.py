import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Conversation, ConversationImpression, Message, User, UserSession, Waitlist
from app.services.identity import guest_user, porch_open_for
from app.services.porch.service import PORCH_CLOSING, PorchService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    Waitlist.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    ConversationImpression.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_start_mints_guest_and_mira_speaks_first(monkeypatch, db) -> None:
    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return "The light is shifting."

    monkeypatch.setattr(
        "app.services.porch.service.get_provider", lambda: FakeProvider()
    )

    conv, opening, ended = None, None, True
    import asyncio

    async def _run():
        nonlocal conv, opening, ended
        conv, opening, ended = await PorchService(db).start(fingerprint="fp-123")

    asyncio.run(_run())

    assert opening == "The light is shifting."
    assert ended is False
    assert conv.kind == "porch"
    user = db.query(User).filter_by(fingerprint="fp-123").first()
    assert user is not None and user.role == "guest"
    first = db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.id).first()
    assert first.speaker == "mira" and first.content == opening


def test_start_is_idempotent_same_porch(monkeypatch, db) -> None:
    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return "The light is shifting."

    monkeypatch.setattr(
        "app.services.porch.service.get_provider", lambda: FakeProvider()
    )
    import asyncio

    async def _start():
        return await PorchService(db).start(fingerprint="fp-456")

    conv1, _, ended1 = asyncio.run(_start())
    conv2, _, ended2 = asyncio.run(_start())
    assert conv1.id == conv2.id
    assert ended1 is False and ended2 is False
    assert db.query(Conversation).filter_by(kind="porch").count() == 1


def test_ended_porch_stays_closed(monkeypatch, db) -> None:
    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return "The light is shifting."

    monkeypatch.setattr(
        "app.services.porch.service.get_provider", lambda: FakeProvider()
    )
    import asyncio

    async def _start():
        return await PorchService(db).start(fingerprint="fp-777")

    conv, _, _ = asyncio.run(_start())
    PorchService(db).end(conv.id)

    conv2, opening, ended = asyncio.run(_start())
    assert conv2.id == conv.id
    assert ended is True
    assert db.query(Conversation).filter_by(kind="porch").count() == 1
    assert opening == "The light is shifting."


def test_end_closes_porch_with_her_words(db) -> None:
    guest = guest_user(db, fingerprint="fp-789")
    conv = Conversation(kind="porch", user_id=guest.id)
    db.add(conv)
    db.flush()
    PorchService(db).end(conv.id)

    db.refresh(conv)
    assert conv.ended_at is not None
    assert porch_open_for(db, guest) is None
    last = db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.id.desc()).first()
    assert last.speaker == "mira" and last.content == PORCH_CLOSING


def test_end_is_idempotent(db) -> None:
    guest = guest_user(db, fingerprint="fp-000")
    conv = Conversation(kind="porch", user_id=guest.id)
    db.add(conv)
    db.flush()
    PorchService(db).end(conv.id)
    PorchService(db).end(conv.id)
    assert db.query(Message).filter_by(conversation_id=conv.id).count() == 1


def test_porch_open_for_only_open_porch(db) -> None:
    guest = guest_user(db, fingerprint="fp-111")
    conv = Conversation(kind="porch", user_id=guest.id)
    other = Conversation(kind="text", user_id=guest.id)
    db.add(conv)
    db.add(other)
    db.flush()

    assert porch_open_for(db, guest) is not None
    assert porch_open_for(db, guest).id == conv.id


def test_verdict_judges_finished_porch_and_keeps_moments_private(monkeypatch, db) -> None:
    guest = guest_user(db, fingerprint="fp-321")
    conv = Conversation(kind="porch", user_id=guest.id)
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, speaker="mira", content="The light is shifting.", source="porch"))
    db.add(Message(conversation_id=conv.id, speaker="user", content="It is. I like that about the evening.", source="text"))
    db.add(Message(conversation_id=conv.id, speaker="mira", content="You notice the light the way I do.", source="text"))
    db.commit()
    PorchService(db).end(conv.id)

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return (
                '{"verdict": "liked", "moments_liked": ["you noticed the light", '
                '"the way you said the evening"], "moments_not_liked": []}'
            )

    monkeypatch.setattr("app.services.porch.service.get_provider", lambda: FakeProvider())

    import asyncio

    asyncio.run(PorchService(db).verdict(conv.id))

    impression = db.query(ConversationImpression).filter_by(conversation_id=conv.id).first()
    assert impression is not None
    assert impression.verdict == "liked"
    assert "you noticed the light" in impression.moments_liked
    assert impression.moments_not_liked == []


def test_verdict_ignores_open_or_non_porch_conversations(monkeypatch, db) -> None:
    guest = guest_user(db, fingerprint="fp-654")
    open_porch = Conversation(kind="porch", user_id=guest.id)
    text = Conversation(kind="text", user_id=guest.id)
    db.add(open_porch)
    db.add(text)
    db.commit()

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return '{"verdict": "liked", "moments_liked": [], "moments_not_liked": []}'

    monkeypatch.setattr("app.services.porch.service.get_provider", lambda: FakeProvider())

    import asyncio

    asyncio.run(PorchService(db).verdict(open_porch.id))
    asyncio.run(PorchService(db).verdict(text.id))

    assert db.query(ConversationImpression).count() == 0
