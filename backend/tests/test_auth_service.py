import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.auth import MagicLink, OAuthState, UserSession
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.models.waitlist import Waitlist
from app.services import identity
from app.services.auth import AuthError, AuthService
from app.services.waitlist.service import WaitlistService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    MagicLink.__table__.create(engine)
    OAuthState.__table__.create(engine)
    Waitlist.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _founder(db) -> User:
    user = User(name="voice", role="founder")
    db.add(user)
    db.commit()
    return user


def _settings(monkeypatch, **overrides) -> None:
    class S:
        session_ttl_days = 30
        smtp_configured = False
        smtp_host = ""
        smtp_user = ""
        smtp_from = ""
        smtp_use_tls = True
        smtp_port = 587
        smtp_password = ""
        mira_access_token = "sekrit"
        jwt_access_token_secret = "sekrit"
        jwt_access_token_ttl_minutes = 15
        bcrypt_rounds = 4
        password_auth_enabled = True
        google_oauth_client_id = "client"
        google_oauth_client_secret = "secret"
        google_oauth_redirect_uri = "https://mira.example/auth/google/callback"
        guest_mode_enabled = False
        guest_message_cap_per_day = 20
        free_user_message_cap_per_day = 60

        @property
        def google_oauth_configured(self) -> bool:
            return bool(self.google_oauth_client_id and self.google_oauth_client_secret)

    for attr, value in overrides.items():
        setattr(S, attr, value)
    monkeypatch.setattr(identity, "get_settings", lambda: S())
    monkeypatch.setattr("app.services.auth.service.get_settings", lambda: S())


# -- sessions -------------------------------------------------------------


def test_session_round_trip(db) -> None:
    user = _founder(db)
    access_token, refresh_token = AuthService(db).create_session(user)
    assert access_token and len(access_token) > 20
    assert refresh_token and len(refresh_token) > 20
    got = AuthService(db).session_user(refresh_token)
    assert got is not None and got.id == user.id


def test_session_unknown_token(db) -> None:
    _founder(db)
    assert AuthService(db).session_user("nope-not-a-real-token") is None


def test_session_revoked(db) -> None:
    user = _founder(db)
    svc = AuthService(db)
    _, refresh_token = svc.create_session(user)
    assert svc.revoke_session(refresh_token) is True
    assert svc.session_user(refresh_token) is None
    assert svc.revoke_session(refresh_token) is True  # idempotent


# -- magic link -----------------------------------------------------------


def test_magic_link_request_and_verify(db) -> None:
    _founder(db)
    svc = AuthService(db)
    code = svc.request_magic_link("Someone@Example.com")
    user, _access_token, refresh_token = svc.verify_magic_link("someone@example.com", code.lower())
    assert user.email == "someone@example.com"
    assert user.role == "person"
    assert AuthService(db).session_user(refresh_token).id == user.id


def test_magic_link_code_is_single_use(db) -> None:
    _founder(db)
    svc = AuthService(db)
    code = svc.request_magic_link("a@b.co")
    svc.verify_magic_link("a@b.co", code)
    assert svc.verify_magic_link("a@b.co", code) is None


def test_magic_link_wrong_code(db) -> None:
    _founder(db)
    svc = AuthService(db)
    svc.request_magic_link("a@b.co")
    assert svc.verify_magic_link("a@b.co", "ZZZZZZZZ") is None


def test_magic_link_expired(db) -> None:
    _founder(db)
    svc = AuthService(db)
    code = svc.request_magic_link("a@b.co")
    row = db.query(MagicLink).one()
    from datetime import timedelta

    row.expires_at = row.expires_at - timedelta(minutes=30)
    db.commit()
    assert svc.verify_magic_link("a@b.co", code) is None


# -- google oauth ---------------------------------------------------------


def test_google_authorize_url_requires_config(monkeypatch, db) -> None:
    _settings(monkeypatch, google_oauth_client_id="", google_oauth_client_secret="")
    with pytest.raises(AuthError):
        AuthService(db).google_authorize_url()


def test_google_authorize_creates_pkce_state(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = AuthService(db)
    url = svc.google_authorize_url()
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "code_challenge=" in url
    row = db.query(OAuthState).one()
    assert row.provider == "google"
    assert row.code_verifier
    assert row.state in url


def test_google_callback_exchange(monkeypatch, db) -> None:
    _settings(monkeypatch)
    svc = AuthService(db)
    url = svc.google_authorize_url()
    import urllib.parse

    state = urllib.parse.parse_qs(url.split("?", 1)[1])["state"][0]

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"access_token": "tok"}

    class _Profile:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"id": "google-123", "email": "guy@gmail.com", "name": "Guy"}

    import app.services.auth.service as auth_module

    monkeypatch.setattr(auth_module.httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(auth_module.httpx, "get", lambda *a, **k: _Profile())

    user, _access_token, refresh_token = svc.google_callback("authcode", state)
    assert user.google_sub == "google-123"
    assert user.email == "guy@gmail.com"
    assert AuthService(db).session_user(refresh_token).id == user.id


# -- identity resolution --------------------------------------------------


def test_resolve_founder_when_no_token_configured(monkeypatch, db) -> None:
    _settings(monkeypatch, mira_access_token="")
    founder = _founder(db)
    assert identity.resolve_user_id(db) == founder.id


def test_resolve_shared_founder_token(monkeypatch, db) -> None:
    _settings(monkeypatch)
    founder = _founder(db)
    assert identity.resolve_user_id(db, x_mira_token="sekrit") == founder.id


def test_resolve_wrong_shared_token_raises(monkeypatch, db) -> None:
    _settings(monkeypatch)
    _founder(db)
    with pytest.raises(Exception):
        identity.resolve_user_id(db, x_mira_token="wrong")


def test_resolve_session_bearer(monkeypatch, db) -> None:
    _settings(monkeypatch)
    _founder(db)
    other = User(name="Nia", role="person", email="nia@x.co")
    db.add(other)
    db.commit()
    token = AuthService(db).create_session(other)[1]  # refresh token
    assert identity.resolve_user_id(db, authorization=f"Bearer {token}") == other.id


def test_resolve_session_via_x_mira_token(monkeypatch, db) -> None:
    """The web app sends every token through X-Mira-Token — a session must
    resolve there too, or signed-in users 401 on a live instance."""
    _settings(monkeypatch)
    _founder(db)
    other = User(name="Nia", role="person", email="nia@x.co")
    db.add(other)
    db.commit()
    token = AuthService(db).create_session(other)[1]  # refresh token
    assert identity.resolve_user_id(db, x_mira_token=token) == other.id
    assert identity.resolve_user_id(db, query_token=token) == other.id


def test_resolve_invalid_bearer_raises(monkeypatch, db) -> None:
    _settings(monkeypatch)
    _founder(db)
    with pytest.raises(Exception):
        identity.resolve_user_id(db, authorization="Bearer bogus-token")


def test_ws_resolution_session_or_founder(monkeypatch, db) -> None:
    _settings(monkeypatch)
    founder = _founder(db)
    _, refresh_token = AuthService(db).create_session(founder)
    assert identity.resolve_ws_user_id(db, token=refresh_token) == founder.id
    assert identity.resolve_ws_user_id(db, token="sekrit") == founder.id
    assert identity.resolve_ws_user_id(db, token="bogus") is None
    assert identity.resolve_ws_user_id(db) is None


# -- guest mode -----------------------------------------------------------


def test_guest_created_and_reused_by_fingerprint(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=True)
    _founder(db)
    first = identity.resolve_request_actor(db, guest_id="device-123", ip="1.2.3.4")
    again = identity.resolve_request_actor(db, guest_id="device-123", ip="9.9.9.9")
    other = identity.resolve_request_actor(db, guest_id="device-456")
    assert first.is_guest and again.is_guest
    assert first.user_id == again.user_id  # same device, same guest world
    assert first.user_id != other.user_id  # different device, different world
    user = db.get(User, first.user_id)
    assert user.role == "guest"
    assert user.last_ip == "9.9.9.9"  # stamped on the latest connection


def test_guest_requires_fingerprint(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=True)
    _founder(db)
    with pytest.raises(Exception):
        identity.resolve_request_actor(db)


def test_no_guest_when_guest_mode_off(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=False)
    _founder(db)
    with pytest.raises(Exception):
        identity.resolve_request_actor(db, guest_id="device-123")


def test_ws_guest_resolution(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=True)
    _founder(db)
    actor = identity.resolve_ws_actor(db, guest_id="device-123")
    assert actor is not None and actor.is_guest
    assert identity.resolve_ws_actor(db) is None  # no guest id, token configured
    assert identity.resolve_ws_user_id(db, token="bogus") is None  # auth-only
    assert identity.resolve_ws_user_id(db) is None  # no guest fallback on this path


def test_ws_guest_ignored_when_guest_mode_off(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=False)
    _founder(db)
    assert identity.resolve_ws_actor(db, guest_id="device-123") is None


# -- the door: first-meeting guests ---------------------------------------


def test_first_meeting_guest_resolves_even_with_guest_mode_off(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=False)
    _founder(db)
    svc = WaitlistService(db)
    svc.signup("door@example.com")
    entry, conv = svc.begin_first_meeting("door@example.com", fingerprint="device-xyz")

    actor = identity.resolve_request_actor(db, guest_id="device-xyz", ip="1.2.3.4")
    assert actor.is_guest and actor.user_id == conv.user_id

    ws = identity.resolve_ws_actor(db, guest_id="device-xyz")
    assert ws is not None and ws.is_guest and ws.user_id == conv.user_id

    svc.end_first_meeting(entry.id, conv.id)
    with pytest.raises(Exception):
        identity.resolve_request_actor(db, guest_id="device-xyz")
    assert identity.resolve_ws_actor(db, guest_id="device-xyz") is None


def test_first_meeting_guest_not_minted_by_resolution(monkeypatch, db) -> None:
    _settings(monkeypatch, guest_mode_enabled=False)
    _founder(db)
    before = db.query(User).count()
    with pytest.raises(Exception):
        identity.resolve_request_actor(db, guest_id="device-stray")
    assert db.query(User).count() == before  # no world minted for a stray


def test_password_sign_up_returns_string_tokens(monkeypatch, db) -> None:
    """Password sign-up must return string access_token and refresh_token,
    not a tuple. Regression test for the create_session tuple bug."""
    _settings(monkeypatch)
    _founder(db)
    auth = AuthService(db)
    user = User(name="alice", role="person", email="alice@example.com")
    db.add(user)
    db.flush()
    auth.set_password(user.id, "s3cret!!")
    db.refresh(user)
    access_token = auth.create_access_token(user)
    _at, refresh_token = auth.create_session(user)
    assert isinstance(access_token, str), f"access_token is {type(access_token)}, not str"
    assert isinstance(refresh_token, str), f"refresh_token is {type(refresh_token)}, not str"
    assert len(access_token) > 10
    assert len(refresh_token) > 10


def test_password_sign_in_returns_string_tokens(monkeypatch, db) -> None:
    """Password sign-in must return (user, str, str). Regression test for the
    create_session tuple bug."""
    _settings(monkeypatch)
    _founder(db)
    auth = AuthService(db)
    user = User(name="bob", role="person", email="bob@example.com")
    db.add(user)
    db.flush()
    auth.set_password(user.id, "p4ss!!!!")
    db.refresh(user)
    result = auth.verify_password("bob@example.com", "p4ss!!!!")
    assert result is not None
    user, access_token, refresh_token = result
    assert isinstance(user, User)
    assert isinstance(access_token, str), f"access_token is {type(access_token)}, not str"
    assert isinstance(refresh_token, str), f"refresh_token is {type(refresh_token)}, not str"
    assert len(access_token) > 10
    assert len(refresh_token) > 10
