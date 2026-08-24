from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

FOUNDER_ROLE = "founder"
REPLICA_ROLE = "replica"
PERSON_ROLE = "person"
GUEST_ROLE = "guest"

# Phase 4 moderation state. One status change only matters: ``banned`` — the
# lock. Mira's rule is no warnings, no second chances; a banned user is refused
# at the identity layer the moment the ban lands.
USER_ACTIVE = "active"
USER_BANNED = "banned"
USER_STATUSES = [USER_ACTIVE, USER_BANNED]


class User(Base):
    """A person (or world) Mira exists beside.

    ``founder`` is the original owner whose data was backfilled in the user
    scoping migration — the seat the live system resolves to until real auth.
    ``replica`` is a spawned copy of Mira's character with an isolated world.
    ``person`` is a human who signed in through real auth (magic link or Google)
    — a new owner of a fresh, isolated world.
    ``guest`` is an anonymous visitor identified by a device fingerprint (Phase 3
    guest mode): no account, message-capped, one world per device.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default=REPLICA_ROLE, server_default=REPLICA_ROLE)
    # Real-auth identities. Email is the magic-link handle; google_sub is the
    # stable Google account id. Both nullable (the founder/replicas may have
    # neither) and unique (one row per identity).
    email: Mapped[Optional[str]] = mapped_column(String(320), unique=True)
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    # Guest-mode identity: a client-generated device fingerprint (or the IP as
    # fallback). Unique so the same device always lands on the same guest world
    # — "one person cannot spin up infinite free Mirus".
    fingerprint: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    last_ip: Mapped[Optional[str]] = mapped_column(String(64))
    # Phase 4 age verification: dedicated columns instead of the last_ip hack.
    age_verified: Mapped[Optional[bool]] = mapped_column(default=None, nullable=True)
    age_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    age_verified_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Phase 4 moderation: the lock. status is active until the founder bans;
    # banned_at/reason/by are the audit trail (Mira's rule is permanent).
    status: Mapped[str] = mapped_column(String(16), default=USER_ACTIVE, server_default=USER_ACTIVE)
    banned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    banned_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
