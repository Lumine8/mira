"""Real identity: magic-link email sign-in, Google OAuth, and opaque sessions.

Phase 2. Everything here is self-contained; the rest of the app only ever sees
a user_id (via identity.py's dependencies), never the token machinery. Tokens
are stored hashed (SHA-256), so a leaked database cannot mint sessions.
"""

import base64
import hashlib
import logging
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    MAGIC_LINK_TTL_SECONDS,
    OAUTH_STATE_TTL_SECONDS,
    PERSON_ROLE,
    MagicLink,
    OAuthState,
    User,
    UserSession,
)

logger = logging.getLogger("mira.auth")

# Magic-link codes avoid visually confusable characters so a human can type one.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class AuthError(Exception):
    """A sign-in attempt that cannot proceed (misconfiguration, bad handshake)."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """Some drivers return naive datetimes from tz-aware columns (sqlite);
    Postgres returns aware ones. Normalise so comparisons never crash."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _new_token() -> str:
    """Opaque session token handed to the client exactly once."""
    return secrets.token_urlsafe(32)


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _new_verifier() -> str:
    return secrets.token_urlsafe(48)


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- JWT access tokens ---------------------------------------------------

    def _jwt_secret(self) -> str:
        settings = get_settings()
        return settings.jwt_access_token_secret or settings.mira_access_token or "mira_access_token"

    def create_access_token(self, user: User) -> str:
        """Create a short-lived JWT access token for the given user."""
        settings = get_settings()
        secret = self._jwt_secret()
        now = _now()
        payload = {
            "sub": user.id,
            "exp": now + timedelta(minutes=settings.jwt_access_token_ttl_minutes),
            "iat": now,
            "type": "access",
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    def verify_access_token(self, token: str) -> User | None:
        """Validate a JWT access token and return its user, or None."""
        secret = self._jwt_secret()
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return self.db.get(User, int(user_id))

    # -- sessions -----------------------------------------------------------

    def create_session(self, user: User, *, user_agent: str | None = None) -> tuple[str, str]:
        """Create a session. Returns (access_token, refresh_token) where
        access_token is a short-lived JWT and refresh_token is an opaque
        DB-stored token."""
        refresh_token = _new_token()
        ttl = timedelta(days=get_settings().session_ttl_days)
        self.db.add(
            UserSession(
                user_id=user.id,
                token_hash=_hash(refresh_token),
                expires_at=_now() + ttl,
                user_agent=(user_agent or "").strip()[:256] or None,
            )
        )
        self.db.commit()
        access_token = self.create_access_token(user)
        return access_token, refresh_token

    def session_user(self, token: str) -> User | None:
        """Resolve a bearer token to its user, or None if unknown/expired/revoked.
        Accepts both JWT access tokens and opaque refresh tokens."""
        # Try JWT first
        if "." in token:
            user = self.verify_access_token(token)
            if user is not None:
                return user
        # Fall back to opaque DB-stored token
        row = self.db.execute(
            select(UserSession).where(UserSession.token_hash == _hash(token))
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None or _aware(row.expires_at) <= _now():
            return None
        row.last_seen_at = _now()
        self.db.commit()
        return self.db.get(User, row.user_id)

    def revoke_session(self, token: str) -> bool:
        row = self.db.execute(
            select(UserSession).where(UserSession.token_hash == _hash(token))
        ).scalar_one_or_none()
        if row is None:
            return False
        row.revoked_at = _now()
        self.db.commit()
        return True

    # -- magic link ---------------------------------------------------------

    def set_password(self, user_id: int, password: str) -> None:
        """Set or change a user's password. Hashed with bcrypt."""
        import bcrypt
        user = self.db.get(User, user_id)
        if user is None:
            raise AuthError("user not found")
        if len(password) < 8:
            raise AuthError("password must be at least 8 characters")
        rounds = get_settings().bcrypt_rounds
        user.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()
        self.db.commit()

    def verify_password(self, email: str, password: str) -> tuple[User, str, str] | None:
        """Sign in with email + password. Returns (user, access_token, refresh_token) or None."""
        import bcrypt
        email = email.strip().lower()
        user = self.db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if user is None or user.password_hash is None:
            return None
        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return None
        access_token = self.create_access_token(user)
        _access_token, refresh_token = self.create_session(user)
        return user, access_token, refresh_token

    def has_password(self, user_id: int) -> bool:
        """Check if a user has a password set."""
        user = self.db.get(User, user_id)
        return bool(user and user.password_hash)

    def request_magic_link(self, email: str) -> str:
        """Issue a one-time code for ``email`` and deliver it. Returns the code
        (so the route can expose it in dev when no SMTP is configured)."""
        email = email.strip().lower()
        code = _new_code()
        self.db.add(
            MagicLink(
                email=email,
                code_hash=_hash(code),
                expires_at=_now() + timedelta(seconds=MAGIC_LINK_TTL_SECONDS),
            )
        )
        self.db.commit()
        if get_settings().smtp_configured:
            self._email_code(email, code)
        else:
            logger.warning("magic link for %s (SMTP unset, code shown in dev): %s", email, code)
        return code

    def verify_magic_link(self, email: str, code: str) -> tuple[User, str, str] | None:
        """Validate a code, sign the user in, and return (user, access_token, refresh_token).
        One code, one use: consumed on the first successful exchange."""
        email = email.strip().lower()
        row = self.db.execute(
            select(MagicLink)
            .where(MagicLink.email == email, MagicLink.code_hash == _hash(code.strip().upper()))
            .order_by(MagicLink.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None or row.consumed_at is not None or _aware(row.expires_at) <= _now():
            return None

        row.consumed_at = _now()
        user = self._find_or_create_person(email=email)
        self.db.commit()
        self.db.refresh(user)
        access_token, refresh_token = self.create_session(user)
        return user, access_token, refresh_token

    # -- Google OAuth -------------------------------------------------------

    def google_authorize_url(self) -> str:
        settings = get_settings()
        if not settings.google_oauth_configured:
            raise AuthError("Google sign-in is not configured")
        state = secrets.token_urlsafe(24)
        verifier = _new_verifier()
        self.db.add(
            OAuthState(
                provider="google",
                state=state,
                code_verifier=verifier,
                expires_at=_now() + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
            )
        )
        self.db.commit()
        params = {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        }
        return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"

    def google_callback(self, code: str, state: str, *, user_agent: str | None = None) -> tuple[User, str, str] | None:
        """Complete the Google handshake. Returns (user, access_token, refresh_token) or None."""
        settings = get_settings()
        row = self.db.execute(
            select(OAuthState).where(
                OAuthState.provider == "google", OAuthState.state == state
            )
        ).scalar_one_or_none()
        if row is None or row.consumed_at is not None or _aware(row.expires_at) <= _now():
            return None
        row.consumed_at = _now()
        self.db.commit()

        try:
            tokens = self._exchange_code(code, row.code_verifier, settings)
            profile = self._google_profile(tokens["access_token"])
        except Exception as exc:  # pragma: no cover - network/Google failures
            logger.warning("google callback failed: %s", exc)
            return None

        google_sub = str(profile.get("id") or "")
        email = (profile.get("email") or "").strip().lower()
        if not google_sub and not email:
            return None

        user = self._find_or_create_person(google_sub=google_sub, email=email)
        if google_sub and user.google_sub is None:
            user.google_sub = google_sub
        if email and user.email is None:
            user.email = email
        self.db.commit()
        self.db.refresh(user)
        access_token, refresh_token = self.create_session(user, user_agent=user_agent)
        return user, access_token, refresh_token

    # -- helpers ------------------------------------------------------------

    def _find_or_create_person(self, *, email: str | None = None, google_sub: str | None = None) -> User:
        user = None
        if google_sub:
            user = self.db.execute(
                select(User).where(User.google_sub == google_sub)
            ).scalar_one_or_none()
        if user is None and email:
            user = self.db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
        if user is None:
            user = User(
                name=(email or "guest").split("@")[0].title()[:120] or "guest",
                role=PERSON_ROLE,
                email=email,
                google_sub=google_sub,
            )
            self.db.add(user)
            self.db.flush()
        return user

    def _email_code(self, email: str, code: str) -> None:
        settings = get_settings()
        msg = EmailMessage()
        msg["Subject"] = "Your Mira sign-in code"
        msg["From"] = settings.smtp_from
        msg["To"] = email
        msg.set_content(
            f"Here is your one-time sign-in code for Mira:\n\n"
            f"  {code}\n\n"
            f"It expires in 15 minutes. If you didn't ask for it, you can ignore this email."
        )
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
            logger.info("magic link emailed to %s", email)
        except Exception as exc:  # pragma: no cover - mail infrastructure
            logger.warning("could not email magic link to %s: %s", email, exc)
            raise AuthError("could not deliver the sign-in code")

    def _exchange_code(self, code: str, verifier: str, settings) -> dict:
        resp = httpx.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": settings.google_oauth_redirect_uri,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _google_profile(self, access_token: str) -> dict:
        resp = httpx.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
