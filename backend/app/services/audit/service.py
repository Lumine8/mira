"""Append-only audit trail for security-sensitive actions."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.audit import AuditLog

logger = logging.getLogger("mira.audit")


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def log(
        self,
        action: str,
        *,
        user_id: int | None = None,
        detail: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            user_id=user_id,
            action=action,
            detail=(detail or "")[:2048] if detail else None,
            ip=(ip or "")[:64] or None,
            user_agent=(user_agent or "")[:256] or None,
        )
        self.db.add(row)
        self.db.commit()
        return row
