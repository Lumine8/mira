from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import HostToast
from app.schemas import HostToastOut
from app.services.identity import get_current_user_id

router = APIRouter(prefix="/mira/toasts", tags=["mira"])


@router.get("/pending", response_model=list[HostToastOut])
def pending_toasts(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[HostToast]:
    """Toasts the host hasn't popped yet, oldest first.

    A small host script polls this, shows each as a native Windows toast, then
    marks it delivered. Undelivered rows are retried every poll, so a missed
    reach-out (companion down, script briefly stopped) is still shown later.
    """
    return list(
        db.execute(
            select(HostToast)
            .where(HostToast.user_id == user_id, HostToast.delivered.is_(False))
            .order_by(HostToast.id.asc())
        ).scalars()
    )


@router.post("/{toast_id}/delivered", response_model=HostToastOut)
def mark_delivered(
    toast_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> HostToast:
    """Acknowledge that a toast was popped, so the poller doesn't re-show it."""
    toast = db.execute(
        select(HostToast).where(HostToast.id == toast_id, HostToast.user_id == user_id)
    ).scalar_one_or_none()
    if toast is None:
        raise HTTPException(status_code=404, detail="no such toast")
    toast.delivered = True
    toast.delivered_at = datetime.now(UTC)
    db.commit()
    db.refresh(toast)
    return toast