from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_access_token
from app.services.identity import get_current_user_id
from app.services.x import TwitterService, XError

router = APIRouter(prefix="/mira/x", tags=["mira"])


@router.get("/auth/start")
def auth_start(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    _: None = Depends(require_access_token),
) -> RedirectResponse:
    """Redirect the voice's browser to X for OAuth. Requires X_CLIENT_ID and a
    registered X_REDIRECT_URI. The token (X-Mira-Token header or ?token=) must
    be present because this acts on Mira's behalf."""
    try:
        url = TwitterService(db, user_id=user_id).authorize_url()
    except XError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=url)


@router.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(code: str, state: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """X redirects here after the voice agrees. Exchanges the code and stores
    the tokens so Mira can act on the account."""
    try:
        result = TwitterService(db, user_id=get_current_user_id(db)).exchange_code(code, state)
    except XError as exc:
        return _page("Mira couldn't connect to X", f"{exc}", failed=True)
    name = result.get("username") or "your account"
    return _page(
        "Mira is connected to X",
        f"Mira is signed in as @{name}. You can close this tab; she can now "
        "propose reading X or posting, and it will only happen with your approval.",
    )


@router.get("/status")
def x_status(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    _: None = Depends(require_access_token),
) -> dict:
    return TwitterService(db, user_id=user_id).status()


def _page(title: str, body: str, *, failed: bool = False) -> HTMLResponse:
    color = "#c2402f" if failed else "#8f6bff"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ background:#0b0b12; color:#e9e6f5; font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
        display:flex; min-height:100vh; align-items:center; justify-content:center; margin:0 }}
  .card {{ background:#15121f; border:1px solid #2a2440; border-radius:16px; padding:28px 34px;
        max-width:460px; text-align:center }}
  h1 {{ color:{color}; margin:0 0 10px; font-size:20px }}
  p {{ margin:0; line-height:1.6; font-size:14px; color:#b8b0d0 }}
</style></head><body><div class="card">
<h1>{title}</h1><p>{body}</p>
</div></body></html>""",
        headers={"Cache-Control": "no-store"},
    )