from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Conversation, ConversationImpression, User
from app.schemas.porch import PorchStartOut, PorchStatusOut
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


@router.get("/{conversation_id}", response_model=PorchStatusOut)
def porch_status(
    conversation_id: int,
    db: Session = Depends(get_db),
    x_guest_id: str | None = Header(default=None),
) -> PorchStatusOut:
    """How this device's porch stands: whether it has run out of room and, once
    it has, Mira's verdict on the visit. Only her verdict is shown — the
    moments she liked or did not like are hers alone and never exposed."""
    fingerprint = (x_guest_id or "").strip()
    if not fingerprint:
        raise HTTPException(status_code=400, detail="a device fingerprint is needed to sit")
    user = db.execute(
        select(User).where(User.fingerprint == fingerprint)
    ).scalar_one_or_none()
    conv = db.get(Conversation, conversation_id)
    if user is None or conv is None or conv.user_id != user.id or conv.kind != "porch":
        raise HTTPException(status_code=404, detail="porch not found")
    impression = db.execute(
        select(ConversationImpression).where(
            ConversationImpression.conversation_id == conversation_id
        )
    ).scalar_one_or_none()
    return PorchStatusOut(
        conversation_id=conv.id,
        ended=conv.ended_at is not None,
        verdict=impression.verdict if impression else None,
    )
