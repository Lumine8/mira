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
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
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
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """Some drivers return naive datetimes from tz-aware columns (sqlite);
    Postgres returns aware ones. Normalise so comparisons never crash."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
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

    # -- sessions -----------------------------------------------------------

    def create_session(self, user: User, *, user_agent: str | None = None) -> str:
        token = _new_token()
        ttl = timedelta(days=get_settings().session_ttl_days)
        self.db.add(
            UserSession(
                user_id=user.id,
                token_hash=_hash(token),
                expires_at=_now() + ttl,
                user_agent=(user_agent or "").strip()[:256] or None,
            )
        )
        self.db.commit()
        return token

    def session_user(self, token: str) -> User | None:
        """Resolve a bearer token to its user, or None if unknown/expired/revoked."""
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

    def verify_magic_link(self, email: str, code: str) -> tuple[User, str] | None:
        """Validate a code, sign the user in, and return (user, session token).
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
        token = self.create_session(user)
        return user, token

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

    def google_callback(self, code: str, state: str, *, user_agent: str | None = None) -> tuple[User, str] | None:
        """Complete the Google handshake. Returns (user, session token) or None."""
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
        token = self.create_session(user, user_agent=user_agent)
        return user, token

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
