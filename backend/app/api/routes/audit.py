from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import FOUNDER_ROLE, User
from app.models.audit import AuditLog
from app.services.identity import get_current_user

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
def list_audit_logs(
    action: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """The founder's audit ledger: who did what, when, from where."""
    if current_user.role != FOUNDER_ROLE:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="only the founder may view audit logs")
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    stmt = stmt.order_by(AuditLog.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "action": r.action,
            "detail": r.detail,
            "ip": r.ip,
            "created_at": r.created_at,
        }
        for r in rows
    ]
