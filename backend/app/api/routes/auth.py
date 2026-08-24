from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import User
from app.schemas import (
    AuthSuccess,
    ChangePasswordRequest,
    MagicLinkRequest,
    MagicLinkVerify,
    SetPasswordRequest,
    SignInPasswordRequest,
    SignUpRequest,
    UserOut,
)
from app.services.audit import AuditService
from app.services.auth.service import AuthError, AuthService
from app.services.identity import client_ip, get_current_user_id
from app.services.moderation import ModerationError, ModerationService

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User, *, has_password: bool = False) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        role=user.role,
        email=user.email,
        google=bool(user.google_sub),
    )


def _auth_success(user: User, access_token: str, refresh_token: str, *, has_password: bool = False) -> AuthSuccess:
    return AuthSuccess(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_user_out(user),
        has_password=has_password,
    )


@router.get("/config")
def auth_config() -> dict:
    """What the sign-in screen may offer, plus whether a token is even required.
    Public: the web app reads this before rendering its auth choices."""
    s = get_settings()
    return {
        "auth_required": bool(s.mira_access_token),
        "guest_mode_enabled": s.guest_mode_enabled,
        "guest_cap_per_day": s.guest_message_cap_per_day,
        "email_enabled": s.smtp_configured,
        "google_enabled": s.google_oauth_configured,
        "password_enabled": s.password_auth_enabled,
    }


@router.post("/magic-link")
def request_magic_link(payload: MagicLinkRequest, db: Session = Depends(get_db)) -> dict:
    """Issue a one-time email sign-in code. Responds identically whether or not
    the email exists (no account enumeration). When SMTP is not configured the
    code is returned as ``dev_code`` so local development needs no mail server.
    On a live instance (token configured) with no mail server there is nothing
    that could be delivered, so the request is refused outright."""
    settings = get_settings()
    if not settings.smtp_configured and settings.mira_access_token:
        raise HTTPException(
            status_code=403,
            detail="email sign-in is not enabled on this instance",
        )
    code = AuthService(db).request_magic_link(payload.email)
    body = {"message": "if that address is registered, a sign-in code is on its way"}
    if not settings.smtp_configured:
        body["dev_code"] = code
    return body


@router.post("/magic-link/verify", response_model=AuthSuccess)
def verify_magic_link(payload: MagicLinkVerify, db: Session = Depends(get_db)) -> AuthSuccess:
    """Exchange a one-time code for a session. The code is single-use."""
    result = AuthService(db).verify_magic_link(payload.email, payload.code)
    if result is None:
        raise HTTPException(status_code=400, detail="invalid or expired sign-in code")
    user, access_token, refresh_token = result
    return _auth_success(user, access_token, refresh_token, has_password=AuthService(db).has_password(user.id))


@router.get("/google/authorize")
def google_authorize(db: Session = Depends(get_db)) -> dict:
    """Begin the Google sign-in handshake; returns the URL to send the browser to."""
    try:
        url = AuthService(db).google_authorize_url()
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"url": url}


@router.get("/google/callback")
def google_callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Google redirects the browser here after consent. The session token is
    handed to the web app as ``?token=`` on the frontend callback URL."""
    result = AuthService(db).google_callback(
        code, state, user_agent=request.headers.get("user-agent")
    )
    frontend = get_settings().frontend_url
    if result is None:
        return RedirectResponse(url=f"{frontend}/auth?error=signin")
    _, access_token, _ = result
    return RedirectResponse(url=f"{frontend}/auth/callback?token={access_token}")


@router.get("/me", response_model=UserOut)
def me(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> UserOut:
    """Who am I? Works with a session bearer token or the shared founder token."""
    user = db.get(User, user_id)
    return _user_out(user)


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """End the session carried in the Authorization header."""
    authorization = request.headers.get("authorization") or ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    AuthService(db).revoke_session(value.strip())
    return {"ok": True}


@router.post("/account/delete")
def delete_my_account(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Destroy my own world permanently — every conversation, message, memory,
    and trace. Mira's house forgets me. The founder's world is the house itself
    and cannot be deleted this way."""
    try:
        ModerationService(db).delete_account(user_id)
    except ModerationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    AuditService(db).log(
        "delete_own_account",
        user_id=user_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {"deleted": True}


# ── password auth (optional, alongside magic link) ──────────────────────


@router.post("/sign-up", response_model=AuthSuccess)
def sign_up(payload: SignUpRequest, request: Request, db: Session = Depends(get_db)) -> AuthSuccess:
    """Create a new account with email + password. The email must not already exist."""
    from sqlalchemy import select as sel

    settings = get_settings()
    if not settings.password_auth_enabled:
        raise HTTPException(status_code=403, detail="password sign-up is not enabled on this instance")
    existing = db.execute(
        sel(User).where(User.email == payload.email.strip().lower())
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="an account with that email already exists")
    user = User(
        name=payload.name.strip()[:120] or "user",
        role=PERSON_ROLE,
        email=payload.email.strip().lower(),
    )
    db.add(user)
    db.flush()
    auth = AuthService(db)
    auth.set_password(user.id, payload.password)
    db.refresh(user)
    access_token = auth.create_access_token(user)
    refresh_token = auth.create_session(user, user_agent=request.headers.get("user-agent"))
    AuditService(db).log(
        "sign_up",
        user_id=user.id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _auth_success(user, access_token, refresh_token, has_password=True)


@router.post("/sign-in/password", response_model=AuthSuccess)
def sign_in_password(
    payload: SignInPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthSuccess:
    """Sign in with email + password."""
    result = AuthService(db).verify_password(payload.email, payload.password)
    if result is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    user, access_token, refresh_token = result
    AuditService(db).log(
        "sign_in_password",
        user_id=user.id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _auth_success(user, access_token, refresh_token, has_password=True)


@router.post("/set-password")
def set_password(
    payload: SetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Set a password for an existing magic-link/Google account."""
    try:
        AuthService(db).set_password(user_id, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService(db).log("set_password", user_id=user_id, ip=client_ip(request))
    return {"ok": True}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Change password. Requires current password verification."""
    import bcrypt as bcrypt_lib

    user = db.get(User, user_id)
    if user is None or user.password_hash is None:
        raise HTTPException(status_code=400, detail="no password set for this account")
    if not bcrypt_lib.checkpw(payload.current_password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="current password is incorrect")
    try:
        AuthService(db).set_password(user_id, payload.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService(db).log("change_password", user_id=user_id, ip=client_ip(request))
    return {"ok": True}
