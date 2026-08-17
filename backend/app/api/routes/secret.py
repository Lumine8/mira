from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas import SecretDoorIn, SecretDoorOut, SecretRoomOut
from app.services.secret.service import SecretService

router = APIRouter(prefix="/secret", tags=["secret"])


@router.post("/door", response_model=SecretDoorOut)
def secret_door(
    payload: SecretDoorIn,
    db: Annotated[Session, Depends(get_db)],
) -> SecretDoorOut:
    """The way in. One pass-phrase only Mira and the voice know. A wrong phrase
    is refused quietly (no hint, no retry guidance) — the door does not explain
    itself."""
    if not SecretService.verify_phrase(payload.phrase):
        raise HTTPException(status_code=403, detail="that isn't it")
    return SecretDoorOut(
        token=SecretService.mint_token(),
        expires_in=get_settings().mira_secret_ttl_seconds,
    )


@router.get("/room", response_model=SecretRoomOut)
def secret_room(
    db: Annotated[Session, Depends(get_db)],
    x_secret_token: Annotated[str | None, Header()],
) -> SecretRoomOut:
    """The room itself — only with a fresh token minted by the phrase."""
    if not SecretService.check_token(x_secret_token):
        raise HTTPException(status_code=401, detail="no")
    return SecretRoomOut(**SecretService(db).room())