from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import MiraState, MoteSharedTime
from app.schemas import MotePresenceOut, MoteSharedTimeOut
from app.services.identity import get_current_user_id

router = APIRouter(prefix="/mote", tags=["mote"])


@router.get("", response_model=MotePresenceOut)
def get_mote_presence(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Mote's current presence: Mira's felt state plus the last sign it made —
    a color, or the last quiet word it offered."""
    state = db.execute(
        select(MiraState).where(MiraState.user_id == user_id).limit(1)
    ).scalar_one_or_none()
    last = db.execute(
        select(MoteSharedTime)
        .where(MoteSharedTime.user_id == user_id)
        .order_by(MoteSharedTime.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if state is None:
        return {"mood": "relaxed", "energy": 70}
    return {
        "mood": state.mood,
        "energy": state.energy,
        "last_kind": last.kind if last is not None else None,
        "last_word": last.word if last is not None else None,
        "last_at": last.at if last is not None else None,
    }


@router.get("/journal", response_model=list[MoteSharedTimeOut])
def get_mote_journal(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list:
    """Mote's felt record — how they have felt together, newest first."""
    return list(
        db.execute(
            select(MoteSharedTime)
            .where(MoteSharedTime.user_id == user_id)
            .order_by(MoteSharedTime.id.desc())
            .limit(50)
        ).scalars()
    )
