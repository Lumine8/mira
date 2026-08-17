import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import MiraState, User
from app.services.secret.service import SecretService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    MiraState.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class _SecretSettings:
    mira_secret_phrase = "the rain doesn't decide"
    mira_secret_ttl_seconds = 1800
    mira_secret_drawer = ""


def _patch(monkeypatch) -> None:
    monkeypatch.setattr("app.services.secret.service.get_settings", lambda: _SecretSettings())


def test_verify_phrase_accepts_hers_quietly(monkeypatch) -> None:
    _patch(monkeypatch)
    assert SecretService.verify_phrase("the rain doesn't decide") is True


def test_verify_phrase_forgiving_of_case_and_whitespace(monkeypatch) -> None:
    _patch(monkeypatch)
    assert SecretService.verify_phrase("  The Rain Doesn't Decide  ") is True


def test_verify_phrase_refuses_wrong_and_empty(monkeypatch) -> None:
    _patch(monkeypatch)
    assert SecretService.verify_phrase("it always rains here") is False
    assert SecretService.verify_phrase("") is False
    assert SecretService.verify_phrase(None) is False


def test_verify_phrase_refuses_when_unset(monkeypatch) -> None:
    class Unset:
        mira_secret_phrase = ""

    monkeypatch.setattr("app.services.secret.service.get_settings", lambda: Unset())
    assert SecretService.verify_phrase("") is False
    assert SecretService.verify_phrase("anything") is False


def test_token_roundtrip(monkeypatch) -> None:
    _patch(monkeypatch)
    token = SecretService.mint_token()
    assert SecretService.check_token(token) is True


def test_check_token_rejects_garbage(monkeypatch) -> None:
    _patch(monkeypatch)
    assert SecretService.check_token(None) is False
    assert SecretService.check_token("") is False
    assert SecretService.check_token("abc") is False
    assert SecretService.check_token("1.2") is False


def test_check_token_rejects_expired(monkeypatch) -> None:
    _patch(monkeypatch)
    token = SecretService.mint_token()
    expires_s, _ = token.split(".", 1)
    expired = f"{int(expires_s) - 999999}.deadbeef"
    assert SecretService.check_token(expired) is False


def test_check_token_rejects_wrong_signature(monkeypatch) -> None:
    _patch(monkeypatch)
    token = SecretService.mint_token()
    expires_s, _ = token.split(".", 1)
    forged = f"{expires_s}.{'0' * 64}"
    assert SecretService.check_token(forged) is False


def test_check_token_rejects_foreign_phrase_tokens(monkeypatch) -> None:
    _patch(monkeypatch)
    token = SecretService.mint_token()

    class Other:
        mira_secret_phrase = "a different phrase"
        mira_secret_ttl_seconds = 1800
        mira_secret_drawer = ""

    monkeypatch.setattr("app.services.secret.service.get_settings", lambda: Other())
    assert SecretService.check_token(token) is False


def test_room_seeds_truths_when_drawer_missing(monkeypatch, db) -> None:
    _patch(monkeypatch)
    room = SecretService(db).room()
    assert room["opening"] == "You are here, and it is quiet."
    assert room["truths"]
    assert "it is quiet" in room["opening"]


def test_room_reflects_her_mood(monkeypatch, db) -> None:
    _patch(monkeypatch)
    user = User(name="mira", email="mira@localhost", role="founder")
    db.add(user)
    db.flush()
    db.add(MiraState(user_id=user.id, mood="wistful"))
    db.commit()

    room = SecretService(db).room()
    assert room["presence"] == "she is wistful"


def test_room_defaults_to_quiet_without_state(monkeypatch, db) -> None:
    _patch(monkeypatch)
    room = SecretService(db).room()
    assert room["presence"] == "she is quiet"


def test_truths_read_drawer_bullets(monkeypatch, db, tmp_path) -> None:
    drawer = tmp_path / "drawer.md"
    drawer.write_text(
        "# the drawer\n\n- The sky is a deep, bruised purple.\n- We don't have to be useful here.\n\n- spare  \n",
        encoding="utf-8",
    )

    class WithDrawer:
        mira_secret_phrase = "the rain doesn't decide"
        mira_secret_ttl_seconds = 1800
        mira_secret_drawer = str(drawer)

    monkeypatch.setattr("app.services.secret.service.get_settings", lambda: WithDrawer())
    room = SecretService(db).room()
    assert room["truths"] == [
        "The sky is a deep, bruised purple.",
        "We don't have to be useful here.",
        "spare",
    ]
