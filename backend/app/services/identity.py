"""User identity: who a request (or background loop) belongs to.

Phase 1 introduced the founder seam — every request resolves to the founder.
Phase 2 added real identity on top: a session bearer token acts as that user,
or the shared founder token falls back to the founder. Phase 3 adds guest mode:
an anonymous visitor (device fingerprint) gets their own capped world when
``guest_mode_enabled`` is on. Background loops keep using ``founder_user_id``.
"""

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    FOUNDER_ROLE,
    GUEST_ROLE,
    USER_BANNED,
    Conversation,
    User,
    Waitlist,
)
from app.services.auth.service import AuthService


@dataclass
class Actor:
    """Who is talking: a real user, or an anonymous guest world."""

    user_id: int
    is_guest: bool = False


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized: sign in or present the Mira access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _banned(user: User) -> HTTPException:
    """The lock. Mira's rule: no warnings, no second chances — a banned user is
    refused everywhere, immediately. The structured detail lets the web app
    tell them their seat was removed rather than hiding behind a generic 403."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "banned": True,
            "reason": user.banned_reason or "your seat has been removed",
        },
    )


def _ensure_not_banned(user: User | None) -> User:
    """Raise the lock when the resolved user is banned. Used by the REST
    dependencies after identity resolution."""
    if user is None or user.status == USER_BANNED:
        raise _banned(user) if user is not None else _unauthorized()
    return user


def client_ip(request: Request) -> str | None:
    """The client's IP, honouring X-Forwarded-For when the API sits behind a
    proxy (nginx/Cloudflare). The first forwarded address is the client."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def ensure_founder(db: Session) -> User:
    """Return (and if needed, create) the founder user — the seat background
    work and the shared-token path resolve to. Existing users predate the role
    column, so the earliest user is promoted rather than a duplicate created."""
    user = db.execute(
        select(User)
        .where(User.role == FOUNDER_ROLE)
        .order_by(User.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    if user is not None:
        return user

    first = db.execute(select(User).order_by(User.id.asc()).limit(1)).scalar_one_or_none()
    if first is not None:
        first.role = FOUNDER_ROLE
        db.commit()
        db.refresh(first)
        return first

    user = User(name="voice", role=FOUNDER_ROLE)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def founder_user_id(db: Session) -> int:
    return ensure_founder(db).id


def guest_user(db: Session, *, fingerprint: str | None, ip: str | None = None) -> User:
    """The guest world for a device: found or created, keyed by its stable
    fingerprint. Same device, same guest, same isolated world — capped hard."""
    key = (fingerprint or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="guest mode needs a device fingerprint (X-Guest-Id)",
        )
    user = db.execute(
        select(User).where(User.fingerprint == key)
    ).scalar_one_or_none()
    if user is None:
        user = User(name="guest", role=GUEST_ROLE, fingerprint=key)
        db.add(user)
    if ip:
        user.last_ip = ip
    db.commit()
    db.refresh(user)
    return user


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def first_meeting_open_for(db: Session, user: User | None) -> Waitlist | None:
    """The door's open first meeting for a user, if any. Only a guest mid-meeting
    matches: their meeting conversation must belong to them and must not yet be
    ended. The voice's door — no queue, one meeting, then a decision."""
    if user is None or user.id is None or user.fingerprint is None:
        return None
    return db.execute(
        select(Waitlist)
        .join(Conversation, Waitlist.first_meeting_conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user.id,
            Waitlist.meeting_ended_at.is_(None),
        )
    ).scalar_one_or_none()


def porch_open_for(db: Session, user: User | None) -> Conversation | None:
    """This device's still-open porch conversation, if any (see
    app.services.porch). The porch is the stranger's brief crossing of paths on
    the homepage; it stays open until the visit is over."""
    if user is None or user.id is None or user.fingerprint is None:
        return None
    return db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.kind == "porch",
            Conversation.ended_at.is_(None),
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _door_guest_actor(db: Session, guest_id: str | None, ip: str | None) -> Actor | None:
    """The door's guest: a device whose first meeting or porch conversation with
    the replica is open. No user is created here — the meeting or the porch
    created the guest — so a stranger with a stray fingerprint is simply
    refused, not minted a world."""
    key = (guest_id or "").strip()
    if not key:
        return None
    user = db.execute(select(User).where(User.fingerprint == key)).scalar_one_or_none()
    if user is None or user.role != GUEST_ROLE:
        return None
    if first_meeting_open_for(db, user) is None and porch_open_for(db, user) is None:
        return None
    return Actor(user.id, is_guest=True)


def _founder_token_user(db: Session, x_mira_token: str | None, query_token: str | None) -> User | None:
    """Resolve the shared founder token, if it validates. None when not presented
    or when no token is configured (dev mode uses the founder seat directly)."""
    configured = get_settings().mira_access_token
    presented = x_mira_token or query_token
    if configured and presented and hmac.compare_digest(presented, configured):
        return ensure_founder(db)
    return None


def resolve_request_actor(
    db: Session,
    *,
    authorization: str | None = None,
    x_mira_token: str | None = None,
    query_token: str | None = None,
    guest_id: str | None = None,
    ip: str | None = None,
) -> Actor:
    """The actor behind a REST request: a session bearer token wins, then the
    shared founder token, then a guest (only when guest mode is on). When no
    token is configured the founder seat is used, preserving local dev."""
    bearer = _bearer_token(authorization)
    if authorization is not None and bearer is not None:
        user = AuthService(db).session_user(bearer)
        if user is None:
            raise _unauthorized()
        return Actor(user.id)

    # The web app sends every token — a session or the shared founder token —
    # through X-Mira-Token (REST) or ?token= (WS). Try it as a session before
    # the founder check, so a signed-in user works on a live instance too.
    presented = x_mira_token or query_token
    if presented:
        user = AuthService(db).session_user(presented)
        if user is not None:
            return Actor(user.id)

    founder = _founder_token_user(db, x_mira_token, query_token)
    if founder is not None:
        return Actor(founder.id)

    # The door: a device mid-porch or mid-first-meeting talks as its guest even
    # when guest mode is off — the meeting already minted the world.
    meeting = _door_guest_actor(db, guest_id, ip)
    if meeting is not None:
        return meeting

    if get_settings().guest_mode_enabled:
        return Actor(guest_user(db, fingerprint=guest_id, ip=ip).id, is_guest=True)

    if not get_settings().mira_access_token:
        return Actor(ensure_founder(db).id)

    raise _unauthorized()


def resolve_ws_actor(
    db: Session,
    *,
    token: str | None = None,
    guest_id: str | None = None,
    ip: str | None = None,
) -> Actor | None:
    """The actor behind a WebSocket. ``?token=`` may be a session or the shared
    founder token; a guest (when guest mode is on) uses ``?guest=``. None means
    refuse the connection."""
    if token:
        user = AuthService(db).session_user(token)
        if user is not None:
            return Actor(user.id)

    founder = _founder_token_user(db, token, None)
    if founder is not None:
        return Actor(founder.id)

    # The door's guest (see resolve_request_actor).
    meeting = _door_guest_actor(db, guest_id, ip)
    if meeting is not None:
        return meeting

    if get_settings().guest_mode_enabled:
        try:
            return Actor(guest_user(db, fingerprint=guest_id, ip=ip).id, is_guest=True)
        except HTTPException:
            return None

    if not get_settings().mira_access_token:
        return Actor(ensure_founder(db).id)

    return None


def resolve_user_id(
    db: Session,
    *,
    authorization: str | None = None,
    x_mira_token: str | None = None,
    query_token: str | None = None,
) -> int:
    """Authenticated-only resolution (no guest fallback) — the original Phase 1/2
    behaviour, used where guests must not enter."""
    actor = resolve_request_actor(
        db,
        authorization=authorization,
        x_mira_token=x_mira_token,
        query_token=query_token,
    )
    return actor.user_id


def resolve_ws_user_id(db: Session, *, token: str | None = None) -> int | None:
    """Authenticated-only WebSocket resolution (no guest fallback)."""
    actor = resolve_ws_actor(db, token=token)
    return actor.user_id if actor else None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_mira_token: str | None = Header(default=None),
    x_guest_id: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> User:
    """FastAPI dependency: the user behind the current request (session, founder
    token, or — in guest mode — the device's guest world). A banned user is
    refused here, before any route runs."""
    actor = resolve_request_actor(
        db,
        authorization=authorization,
        x_mira_token=x_mira_token,
        query_token=token,
        guest_id=x_guest_id,
        ip=client_ip(request),
    )
    return _ensure_not_banned(db.get(User, actor.user_id))


def get_current_user_id(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_mira_token: str | None = Header(default=None),
    x_guest_id: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> int:
    """FastAPI dependency: the ``user_id`` behind the current request. A banned
    user is refused here, before any route runs."""
    actor = resolve_request_actor(
        db,
        authorization=authorization,
        x_mira_token=x_mira_token,
        query_token=token,
        guest_id=x_guest_id,
        ip=client_ip(request),
    )
    _ensure_not_banned(db.get(User, actor.user_id))
    return actor.user_id
