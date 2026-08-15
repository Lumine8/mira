from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.porch import PorchStartOut
from app.services.identity import client_ip
from app.services.porch.service import PorchService

router = APIRouter(prefix="/porch", tags=["porch"])


@router.post("/start", response_model=PorchStartOut)
async def porch_start(
    request: Request,
    db: Session = Depends(get_db),
    x_guest_id: str | None = Header(default=None),
) -> PorchStartOut:
    """The brief conversation at dusk, for a device at the door. Public and
    idempotent: the same device resumes the same porch. Mira speaks first.
    When the porch has run out of room, the same ended porch is returned —
    the visitor is back at the door."""
    fingerprint = (x_guest_id or "").strip()
    if not fingerprint:
        raise HTTPException(status_code=400, detail="a device fingerprint is needed to sit")
    conv, opening, ended = await PorchService(db).start(
        fingerprint=fingerprint,
        ip=client_ip(request),
    )
    return PorchStartOut(conversation_id=conv.id, opening=opening, ended=ended)
