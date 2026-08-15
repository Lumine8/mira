from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# How long each artifact stays usable before it must be re-issued. Magic links
# are short (a link in an inbox shouldn't work forever); Google OAuth states are
# short (a browser redirect must be quick); sessions are long (the voice stays
# signed in across days without being pestered).
MAGIC_LINK_TTL_SECONDS = 15 * 60
OAUTH_STATE_TTL_SECONDS = 10 * 60
SESSION_TTL_DAYS = 30


class UserSession(Base):
    """An authenticated session: an opaque bearer token.

    Only the SHA-256 of the token is stored, so a leaked database cannot mint
    sessions. A session is usable until its expiry and only while ``revoked_at``
    is unset — revocation is how logout (or, later, exclusion) ends it instantly.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[Optional[str]] = mapped_column(String(256))


class MagicLink(Base):
    """A one-time email sign-in code.

    The plaintext code is given to the user once (email, or the dev response)
    and only its hash is stored. One code, one use, short life.
    """

    __tablename__ = "magic_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class OAuthState(Base):
    """A browser-OAuth handshake record (Google PKCE).

    The ``state`` guards against CSRF (the callback must present the same
    random state we issued) and also carries the PKCE ``code_verifier`` so the
    token exchange can prove the request came from this server.
    """

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(64), unique=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
