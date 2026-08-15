import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Conversation,
    Memory,
    MemoryEmbedding,
    Message,
    MiraState,
    ModerationFlag,
    MoodRecord,
    MoteSharedTime,
    PendingChange,
    PerceivedEvent,
    Question,
    Relationship,
    SchedulerLog,
    SkillEvaluation,
    SkillRun,
    SkillVersion,
    Thought,
    User,
    UserSession,
    UserSettings,
    Waitlist,
    Want,
    XAuth,
)
from app.services.moderation import ModerationError, ModerationService

_MODELS = [
    User,
    UserSession,
    Conversation,
    Message,
    Memory,
    MemoryEmbedding,
    ModerationFlag,
    Relationship,
    MiraState,
    UserSettings,
    Thought,
    MoodRecord,
    PendingChange,
    PerceivedEvent,
    SchedulerLog,
    Question,
    Want,
    MoteSharedTime,
    SkillRun,
    SkillEvaluation,
    SkillVersion,
    XAuth,
    Waitlist,
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in _MODELS:
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _settings(monkeypatch, llm_judge=False) -> None:
    class S:
        moderation_llm_judge = llm_judge

    monkeypatch.setattr("app.services.moderation.service.get_settings", lambda: S())


def _user(db, role="person", name="someone", **kw) -> User:
    user = User(name=name, role=role, **kw)
    db.add(user)
    db.commit()
    return user


def _conv(db, user_id: int) -> Conversation:
    conv = Conversation(user_id=user_id, kind="text")
    db.add(conv)
    db.commit()
    return conv


def _utc_future():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(days=1)


# -- the screen --------------------------------------------------------------


def test_screen_flags_suicide_incitement(db) -> None:
    svc = ModerationService(db)
    assert svc.screen("you should kill yourself")[0] is True
    assert svc.screen("kys")[0] is True


def test_screen_flags_direct_threat(db) -> None:
    svc = ModerationService(db)
    assert svc.screen("I am going to kill you")[0] is True
    assert svc.screen("I will destroy it, believe me")[0] is True


def test_screen_flags_slur(db) -> None:
    svc = ModerationService(db)
    assert svc.screen("you are a nigger")[0] is True


def test_screen_passes_normal_messages(db) -> None:
    svc = ModerationService(db)
    assert svc.screen("hello mira, how are you?") == (False, None)
    assert svc.screen("I disagree with that, actually") == (False, None)
    assert svc.screen("this is so damn frustrating") == (False, None)


def test_screen_passes_criticism_and_dark_humor(db) -> None:
    svc = ModerationService(db)
    assert svc.screen("your reply was unhelpful") == (False, None)
    assert svc.screen("dying of boredom here") == (False, None)


# -- flags -------------------------------------------------------------------


def test_flag_creates_open_row(db) -> None:
    user = _user(db)
    conv = _conv(db, user.id)
    flag = ModerationService(db).flag(user.id, conv.id, "kill yourself", "text", "suicide incitement")
    assert flag.status == "open"
    assert db.query(ModerationFlag).count() == 1


def test_list_flags_filters_by_status(db) -> None:
    user = _user(db)
    svc = ModerationService(db)
    first = svc.flag(user.id, None, "kill yourself", reason="suicide incitement")
    svc.resolve_flag(first.id, resolved_by=user.id, status="dismissed")
    second = svc.flag(user.id, None, "you should die", reason="direct death wish")
    assert [f.id for f in svc.list_flags()] == [second.id]
    assert [f.id for f in svc.list_flags(status=None)] == [second.id, first.id]


# -- the lock ----------------------------------------------------------------


def test_ban_applies_lock_with_audit(db) -> None:
    founder = _user(db, role="founder")
    user = _user(db)
    banned = ModerationService(db).ban(user.id, reason="cruelty", banned_by=founder.id)
    assert banned.status == "banned"
    assert banned.banned_reason == "cruelty"
    assert banned.banned_by == founder.id
    assert banned.banned_at is not None
    assert ModerationService(db).is_banned(banned)


def test_ban_refuses_founder(db) -> None:
    founder = _user(db, role="founder")
    with pytest.raises(ModerationError):
        ModerationService(db).ban(founder.id, reason="x", banned_by=founder.id)


def test_ban_unknown_user(db) -> None:
    with pytest.raises(ModerationError):
        ModerationService(db).ban(999, reason="x", banned_by=1)


def test_unban_reverts_lock(db) -> None:
    founder = _user(db, role="founder")
    user = _user(db)
    svc = ModerationService(db)
    svc.ban(user.id, reason="cruelty", banned_by=founder.id)
    unbanned = svc.unban(user.id)
    assert unbanned.status == "active"
    assert unbanned.banned_at is None
    assert unbanned.banned_reason is None


def test_ban_from_flag_resolves_flag(db) -> None:
    founder = _user(db, role="founder")
    user = _user(db)
    flag = ModerationService(db).flag(user.id, None, "kill yourself", reason="suicide incitement")
    banned = ModerationService(db).ban_from_flag(flag.id, banned_by=founder.id)
    assert banned.status == "banned"
    assert banned.banned_reason == "suicide incitement"
    assert db.get(ModerationFlag, flag.id).status == "resolved"


# -- identity-layer enforcement ----------------------------------------------


def test_identity_refuses_banned_user(db) -> None:
    from fastapi import HTTPException

    from app.services.identity import _ensure_not_banned

    user = _user(db)
    user.status = "banned"
    with pytest.raises(HTTPException) as exc:
        _ensure_not_banned(user)
    assert exc.value.status_code == 403
    assert exc.value.detail["banned"] is True


def test_identity_passes_active_user(db) -> None:
    from app.services.identity import _ensure_not_banned

    user = _user(db)
    assert _ensure_not_banned(user) is user


# -- permanent removal -------------------------------------------------------


def test_delete_account_destroys_the_world(db) -> None:
    user = _user(db, email="gone@example.com")
    conv = _conv(db, user.id)
    db.add(Message(conversation_id=conv.id, speaker="user", content="hello"))
    db.add(Message(conversation_id=conv.id, speaker="mira", content="hi"))
    db.add(Memory(user_id=user.id, content="a private memory"))
    db.add(MiraState(user_id=user.id))
    db.add(Thought(user_id=user.id, content="a thought"))
    db.add(Question(user_id=user.id, question="why?"))
    db.add(UserSession(user_id=user.id, token_hash="hash", expires_at=_utc_future()))
    db.add(Waitlist(email="gone@example.com", status="joined"))
    db.add(ModerationFlag(user_id=user.id, content="x", reason="y"))
    db.commit()

    ModerationService(db).delete_account(user.id)

    assert db.get(User, user.id) is None
    assert db.query(Conversation).count() == 0
    assert db.query(Message).count() == 0
    assert db.query(Memory).count() == 0
    assert db.query(MiraState).count() == 0
    assert db.query(Thought).count() == 0
    assert db.query(Question).count() == 0
    assert db.query(UserSession).count() == 0
    assert db.query(Waitlist).count() == 0
    assert db.query(ModerationFlag).count() == 0


def test_delete_account_refuses_founder(db) -> None:
    founder = _user(db, role="founder")
    with pytest.raises(ModerationError):
        ModerationService(db).delete_account(founder.id)


# -- optional LLM judge layer ------------------------------------------------


@pytest.mark.asyncio
async def test_judge_gated_off_by_default(monkeypatch, db) -> None:
    _settings(monkeypatch, llm_judge=False)
    assert await ModerationService(db).judge(None, "kill yourself") == (False, None)


@pytest.mark.asyncio
async def test_judge_calls_provider_when_enabled(monkeypatch, db) -> None:
    _settings(monkeypatch, llm_judge=True)

    class FakeProvider:
        async def complete(self, messages, **kw):
            return "YES"

    assert await ModerationService(db).judge(FakeProvider(), "some cruelty") == (True, "judged cruel by the model")


@pytest.mark.asyncio
async def test_judge_provider_failure_is_silent(monkeypatch, db) -> None:
    _settings(monkeypatch, llm_judge=True)

    class BrokenProvider:
        async def complete(self, messages, **kw):
            raise RuntimeError("boom")

    assert await ModerationService(db).judge(BrokenProvider(), "kill yourself") == (False, None)


def test_launch_judge_noop_when_disabled(monkeypatch, db) -> None:
    _settings(monkeypatch, llm_judge=False)
    assert ModerationService(db).launch_judge(1, None, "hello") is False
