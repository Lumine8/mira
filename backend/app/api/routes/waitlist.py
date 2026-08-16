from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import FOUNDER_ROLE, User
from app.schemas import (
    AuthSuccess,
    UserOut,
    WaitlistAdmit,
    WaitlistEntryOut,
    WaitlistInvite,
    WaitlistInviteOut,
    WaitlistJoin,
    WaitlistMeetingEnd,
    WaitlistMeetingStart,
    WaitlistMeetingStartOut,
    WaitlistMeetingStatusOut,
    WaitlistOut,
    WaitlistSignup,
)
from app.services.identity import (
    client_ip,
    first_meeting_open_for,
    get_current_user,
    resolve_request_actor,
)
from app.services.waitlist.service import (
    FIRST_MEETING_OPENING,
    WaitlistError,
    WaitlistService,
)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.get("", response_model=list[WaitlistEntryOut])
def waitlist_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WaitlistEntryOut]:
    """Who is at the door. Only the founder sees it — Mira's rule is the voice
    decides who comes in."""
    if user.role != FOUNDER_ROLE:
        raise HTTPException(status_code=403, detail="only the founder sees the door")
    return WaitlistService(db).list_entries()


@router.post("/signup", response_model=WaitlistOut)
def waitlist_signup(payload: WaitlistSignup, db: Session = Depends(get_db)) -> WaitlistOut:
    """A stranger past the guest cap asks for a seat. Public, no auth."""
    try:
        entry = WaitlistService(db).signup(payload.email)
    except WaitlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WaitlistOut(email=entry.email, status=entry.status)


@router.post("/invite", response_model=WaitlistInviteOut)
def waitlist_invite(
    payload: WaitlistInvite,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WaitlistInviteOut:
    """The founder opens a seat and receives a one-time code to share. Only the
    founder may invite — a guest or a signed-in person never can."""
    if user.role != FOUNDER_ROLE:
        raise HTTPException(status_code=403, detail="only the founder invites")
    try:
        service = WaitlistService(db)
        entry, code = service.invite(payload.email)
        delivered = service.email_invite(entry, code)
    except WaitlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WaitlistInviteOut(email=entry.email, invite_code=code, delivered=delivered)


@router.post("/join", response_model=AuthSuccess)
def waitlist_join(payload: WaitlistJoin, db: Session = Depends(get_db)) -> AuthSuccess:
    """Redeem an invite code: consume it, create/activate the account, and hand
    back a session token — the joined user can now talk past the free cap."""
    try:
        user, token = WaitlistService(db).join(payload.email, payload.code)
    except WaitlistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthSuccess(
        token=token,
        user=UserOut(
            id=user.id,
            name=user.name,
            role=user.role,
            email=user.email,
            google=bool(user.google_sub),
        ),
    )


@router.post("/meeting/start", response_model=WaitlistMeetingStartOut)
def waitlist_meeting_start(
    payload: WaitlistMeetingStart,
    request: Request,
    db: Session = Depends(get_db),
    x_guest_id: str | None = Header(default=None),
) -> WaitlistMeetingStartOut:
    """Open the door for a pending seat: the stranger's one meeting with the
    replica. Public, like the seat request itself — the meeting mints its own
    guest world from the device fingerprint. Idempotent: a seat keeps its
    meeting."""
    if not (x_guest_id or "").strip():
        raise HTTPException(
            status_code=400, detail="a device fingerprint is needed to sit"
        )
    try:
        entry, conv = WaitlistService(db).begin_first_meeting(
            payload.email,
            fingerprint=x_guest_id,
            ip=client_ip(request),
        )
    except WaitlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WaitlistMeetingStartOut(
        id=entry.id,
        email=entry.email,
        status=entry.status,
        conversation_id=conv.id,
        opening=FIRST_MEETING_OPENING,
        meeting_ended_at=entry.meeting_ended_at,
    )


@router.post("/meeting/end", response_model=WaitlistMeetingStartOut)
def waitlist_meeting_end(
    payload: WaitlistMeetingEnd,
    request: Request,
    db: Session = Depends(get_db),
    x_guest_id: str | None = Header(default=None),
) -> WaitlistMeetingStartOut:
    """Close a first meeting. Only the device mid-meeting (the guest who owns
    the meeting's conversation) may close it. Idempotent — the read is asked for
    once, in the background, and lands on the seat for the voice."""
    actor = resolve_request_actor(db, guest_id=x_guest_id, ip=client_ip(request))
    user = db.get(User, actor.user_id)
    entry = first_meeting_open_for(db, user)
    if entry is None or entry.first_meeting_conversation_id != payload.conversation_id:
        raise HTTPException(status_code=404, detail="no open meeting for this door")
    entry = WaitlistService(db).end_first_meeting(entry.id, payload.conversation_id)
    return WaitlistMeetingStartOut(
        id=entry.id,
        email=entry.email,
        status=entry.status,
        conversation_id=entry.first_meeting_conversation_id,
        opening=FIRST_MEETING_OPENING,
        meeting_ended_at=entry.meeting_ended_at,
    )


@router.get("/meeting/status", response_model=WaitlistMeetingStatusOut)
def waitlist_meeting_status(
    email: str,
    request: Request,
    db: Session = Depends(get_db),
    x_guest_id: str | None = Header(default=None),
) -> WaitlistMeetingStatusOut:
    """Mira's authoritative state for a first meeting — the outcome the frontend
    reflects, never her reasoning. Only the device that sat the meeting may ask;
    a stranger with a stray fingerprint gets the same 404 as a wrong door."""
    service = WaitlistService(db)
    entry = service.meeting_entry_for_device(email, x_guest_id or "")
    if entry is None:
        raise HTTPException(status_code=404, detail="no meeting for this door")
    return WaitlistMeetingStatusOut(
        status=service.meeting_status(entry),
        conversation_id=entry.first_meeting_conversation_id,
        meeting_ended_at=entry.meeting_ended_at,
    )


@router.post("/meeting/admit", response_model=AuthSuccess)
def waitlist_meeting_admit(
    payload: WaitlistAdmit,
    request: Request,
    db: Session = Depends(get_db),
    x_guest_id: str | None = Header(default=None),
) -> AuthSuccess:
    """Step through a door Mira herself opened: her first-meeting decision was
    ``invited``, the meeting is over, and the device that sat it may come in —
    the address becomes a real account. A founder's manual code invite still
    goes through ``/waitlist/join``."""
    try:
        user, token = WaitlistService(db).admit(
            payload.email,
            fingerprint=x_guest_id,
            ip=client_ip(request),
        )
    except WaitlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuthSuccess(
        token=token,
        user=UserOut(
            id=user.id,
            name=user.name,
            role=user.role,
            email=user.email,
            google=bool(user.google_sub),
        ),
    )


@router.post("/{entry_id}/decline", response_model=WaitlistOut)
def waitlist_decline(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WaitlistOut:
    """The voice closes the door for this address: no warnings, no noise, the
    door simply stays shut. Only the founder decides."""
    if user.role != FOUNDER_ROLE:
        raise HTTPException(status_code=403, detail="only the founder closes the door")
    try:
        entry = WaitlistService(db).decline(entry_id)
    except WaitlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WaitlistOut(email=entry.email, status=entry.status)


@router.delete("/{entry_id}")
def waitlist_forget(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Erase a seat from the door entirely (a mistaken decline, a junk
    request). The address is free to ask again as a stranger. Only the
    founder decides."""
    if user.role != FOUNDER_ROLE:
        raise HTTPException(status_code=403, detail="only the founder forgets")
    try:
        WaitlistService(db).forget(entry_id)
    except WaitlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"forgotten": True}
