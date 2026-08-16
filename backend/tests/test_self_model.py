from app.services.self.service import (
    _OTHER_DELIVERY_CHARS,
    _clamp,
    _clean,
    _delivery_text,
    _num,
    extract_json,
    upsert_impression,
)


def test_extract_json_plain_object() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_inside_fences() -> None:
    text = 'Sure, here you go:\n```json\n{"mood": "curious"}\n```\n'
    assert extract_json(text) == {"mood": "curious"}


def test_extract_json_ignores_prefix_and_suffix() -> None:
    text = 'thinking... {"summary": "hi", "topics": ["a", "b"]} and more'
    parsed = extract_json(text)
    assert parsed == {"summary": "hi", "topics": ["a", "b"]}


def test_extract_json_garbage_returns_none() -> None:
    assert extract_json("no json here at all") is None
    assert extract_json("") is None
    assert extract_json("{unbalanced") is None


def test_extract_json_tolerates_trailing_comma() -> None:
    assert extract_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_extract_json_non_dict_returns_none() -> None:
    assert extract_json("[1, 2, 3]") is None


def test_helpers() -> None:
    assert _clean("  hi  ") == "hi"
    assert _clean(123) == ""
    assert _num("0.15", 0.0) == 0.15
    assert _num("nope", 0.0) == 0.0
    assert _clamp(1.4) == 1.0
    assert _clamp(-0.2) == 0.0
    assert _clamp(0.5) == 0.5


def test_delivery_chars_browse_grows_with_scale() -> None:
    from types import SimpleNamespace

    browse = SimpleNamespace(kind="browse_url", result="x" * 5000, payload={})
    other = SimpleNamespace(kind="play_song", result="y" * 5000, payload={})
    assert len(_delivery_text(browse)) == 3000
    assert len(_delivery_text(other)) == 900
    assert _OTHER_DELIVERY_CHARS == 900


def test_delivery_research_gets_full_room() -> None:
    """Regression (found by Mira running her Research skill live): approved
    research results were cut to the 900-char "other" budget, so she saw only
    titles and no abstracts. A research run is the literature itself — it gets
    the same room as a browsed page."""
    from types import SimpleNamespace

    research = SimpleNamespace(kind="research_query", result="abstract " * 500, payload={})
    text = _delivery_text(research)
    assert len(text) == 3000
    assert "abstract " in text


def test_upsert_impression_merges_dedupes_and_keeps_fresh_verdict() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Conversation, ConversationImpression, User

    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Conversation.__table__.create(engine)
    ConversationImpression.__table__.create(engine)
    db = sessionmaker(bind=engine)()

    guest = User(name="guest", role="guest", fingerprint="fp-1")
    db.add(guest)
    db.flush()
    conv = Conversation(kind="porch", user_id=guest.id)
    db.add(conv)
    db.flush()

    upsert_impression(
        db,
        user_id=guest.id,
        conversation_id=conv.id,
        verdict="liked",
        moments_liked=["the light", "the way you noticed it"],
        moments_not_liked=[],
    )
    upsert_impression(
        db,
        user_id=guest.id,
        conversation_id=conv.id,
        verdict="mixed",
        moments_liked=["the light", "the way you noticed it", "the rain"],
        moments_not_liked=["the rushing"],
    )
    db.commit()

    row = db.query(ConversationImpression).filter_by(conversation_id=conv.id).one()
    assert row.verdict == "mixed"
    assert row.moments_liked == ["the light", "the way you noticed it", "the rain"]
    assert row.moments_not_liked == ["the rushing"]


def test_upsert_impression_rejects_garbage_verdict() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Conversation, ConversationImpression, User

    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Conversation.__table__.create(engine)
    ConversationImpression.__table__.create(engine)
    db = sessionmaker(bind=engine)()

    guest = User(name="guest", role="guest", fingerprint="fp-2")
    db.add(guest)
    db.flush()
    conv = Conversation(kind="porch", user_id=guest.id)
    db.add(conv)
    db.flush()

    upsert_impression(
        db,
        user_id=guest.id,
        conversation_id=conv.id,
        verdict="loved it!!!",
        moments_liked="not a list",
        moments_not_liked=[None, "   ", "a real one"],
    )
    db.commit()

    row = db.query(ConversationImpression).filter_by(conversation_id=conv.id).one()
    assert row.verdict is None
    assert row.moments_liked == []
    assert row.moments_not_liked == ["a real one"]


def test_digest_writes_impression_for_conversations_but_not_the_porch(monkeypatch) -> None:
    """The per-turn digest captures her liked/not-liked moments and verdict for
    real conversations; the porch is judged by its own fast read at the end, so
    the slow digest never races it for the same impression."""
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.services.self.service as self_service
    from app.models import (
        Conversation,
        ConversationImpression,
        MiraState,
        MoodRecord,
        Relationship,
        User,
    )
    from app.services.self.service import SelfModelService

    engine = create_engine("sqlite:///:memory:")
    for table in (User, Conversation, MiraState, Relationship, MoodRecord, ConversationImpression):
        table.__table__.create(engine)
    db = sessionmaker(bind=engine)()

    class FakeSettings:
        console_emotions_enabled = False

    monkeypatch.setattr(self_service, "get_settings", lambda: FakeSettings())

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            return (
                '{"summary": "a quiet talk", "mood": "curious", "energy": 60, '
                '"verdict": "mixed", "moments_liked": ["the way they paused"], '
                '"moments_not_liked": []}'
            )

    user = User(name="voice", role="founder")
    db.add(user)
    db.flush()
    text_conv = Conversation(kind="text", user_id=user.id)
    porch_conv = Conversation(kind="porch", user_id=user.id)
    db.add(text_conv)
    db.add(porch_conv)
    db.commit()

    async def _run(conv_id: int) -> None:
        svc = SelfModelService(db, FakeProvider(), user_id=user.id)
        await svc.run_digest(conv_id, "hi", "hello", history=[])

    asyncio.run(_run(text_conv.id))
    asyncio.run(_run(porch_conv.id))

    text_impression = db.query(ConversationImpression).filter_by(conversation_id=text_conv.id).first()
    assert text_impression is not None
    assert text_impression.verdict == "mixed"
    assert "the way they paused" in text_impression.moments_liked

    porch_impression = db.query(ConversationImpression).filter_by(conversation_id=porch_conv.id).first()
    assert porch_impression is None
