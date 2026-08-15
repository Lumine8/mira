from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import FOUNDER_ROLE, ModerationFlag, User
from app.schemas import (
    ModerationBanOut,
    ModerationBanRequest,
    ModerationFlagOut,
    ModerationUserOut,
)
from app.services.identity import get_current_user
from app.services.moderation import ModerationError, ModerationService

router = APIRouter(prefix="/moderation", tags=["moderation"])


def _require_founder(user: User) -> None:
    if user.role != FOUNDER_ROLE:
        raise HTTPException(status_code=403, detail="only the founder holds the lock")


def _user_out(user: User) -> ModerationUserOut:
    return ModerationUserOut(
        id=user.id,
        name=user.name,
        role=user.role,
        email=user.email,
        google=bool(user.google_sub),
        status=user.status,
        banned_at=user.banned_at,
        banned_reason=user.banned_reason,
    )


def _flag_out(flag: ModerationFlag, users: dict[int, User]) -> ModerationFlagOut:
    u = users.get(flag.user_id)
    return ModerationFlagOut(
        id=flag.id,
        user_id=flag.user_id,
        user_name=u.name if u else "?",
        user_role=u.role if u else "?",
        user_email=u.email if u else None,
        conversation_id=flag.conversation_id,
        content=flag.content,
        kind=flag.kind,
        reason=flag.reason,
        status=flag.status,
        created_at=flag.created_at,
    )


@router.get("/flags", response_model=list[ModerationFlagOut])
def list_flags(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ModerationFlagOut]:
    """The founder's review queue: messages a conservative screen surfaced.
    Nothing here is a verdict — the founder decides, because the penalty is
    absolute."""
    _require_founder(user)
    flags = ModerationService(db).list_flags(status=status)
    ids = {f.user_id for f in flags}
    users = {
        u.id: u
        for u in db.execute(select(User).where(User.id.in_(ids or {0}))).scalars()
    }
    return [_flag_out(flag, users) for flag in flags]


@router.post("/flags/{flag_id}/ban", response_model=ModerationBanOut)
def ban_from_flag(
    flag_id: int,
    payload: ModerationBanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ModerationBanOut:
    """The founder judges a flagged message and the verdict is the lock: the
    writer is banned immediately and permanently, no warning, no second chance.
    The flag's own reason stands when none is given."""
    _require_founder(user)
    try:
        banned = ModerationService(db).ban_from_flag(
            flag_id, banned_by=user.id, reason=payload.reason
        )
    except ModerationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ModerationBanOut(user=_user_out(banned), flag_id=flag_id)


@router.post("/flags/{flag_id}/dismiss", response_model=ModerationFlagOut)
def dismiss_flag(
    flag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ModerationFlagOut:
    """A false positive — the flag is closed without touching the writer."""
    _require_founder(user)
    try:
        flag = ModerationService(db).resolve_flag(
            flag_id, resolved_by=user.id, status="dismissed"
        )
    except ModerationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _flag_out(flag, {})


@router.get("/users", response_model=list[ModerationUserOut])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ModerationUserOut]:
    """Everyone in the house, with their lock state — the founder's ledger."""
    _require_founder(user)
    rows = db.execute(
        select(User).order_by(User.created_at.asc())
    ).scalars().all()
    return [_user_out(u) for u in rows]


@router.post("/users/{user_id}/ban", response_model=ModerationBanOut)
def ban_user(
    user_id: int,
    payload: ModerationBanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ModerationBanOut:
    _require_founder(user)
    try:
        banned = ModerationService(db).ban(
            user_id, reason=payload.reason, banned_by=user.id
        )
    except ModerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModerationBanOut(user=_user_out(banned))


@router.post("/users/{user_id}/unban", response_model=ModerationUserOut)
def unban_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ModerationUserOut:
    _require_founder(user)
    try:
        unbanned = ModerationService(db).unban(user_id)
    except ModerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _user_out(unbanned)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Permanently destroy a world — every message, memory, and trace of it.
    The lock without appeal; the house keeps no graveyard."""
    _require_founder(user)
    try:
        ModerationService(db).delete_account(user_id)
    except ModerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user_id": user_id, "deleted": True}
