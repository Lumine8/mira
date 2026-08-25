"""Job queue with SELECT FOR UPDATE SKIP LOCKED for safe multi-worker
consumption. Each worker claims jobs atomically; stale locks are reclaimed
after a timeout."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.models.job import (
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)

logger = logging.getLogger("mira.jobs")

_LOCK_TIMEOUT_MINUTES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobService:
    """Stateless helper: each method opens its own session so jobs are
    independent of the caller's transaction."""

    def enqueue(self, kind: str, *, user_id: int | None = None, payload: dict | None = None) -> int:
        db = SessionLocal()
        try:
            job = BackgroundJob(
                kind=kind,
                user_id=user_id,
                payload=payload or {},
                status=JOB_PENDING,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            return job.id
        finally:
            db.close()

    def claim(self, worker_id: str | None = None, *, kinds: list[str] | None = None) -> BackgroundJob | None:
        """Atomically claim the next pending job of the given kind(s). Returns
        None when the queue is empty. Uses SELECT FOR UPDATE SKIP LOCKED so
        concurrent workers never collide."""
        db = SessionLocal()
        try:
            worker = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
            stmt = (
                select(BackgroundJob)
                .where(
                    BackgroundJob.status.in_([JOB_PENDING, JOB_RUNNING]),
                    BackgroundJob.locked_by.is_(None),
                )
                .order_by(BackgroundJob.id.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if kinds:
                stmt = stmt.where(BackgroundJob.kind.in_(kinds))

            row = db.execute(stmt).scalar_one_or_none()
            if row is None:
                # Reclaim stale locks
                stale_cutoff = _now() - timedelta(minutes=_LOCK_TIMEOUT_MINUTES)
                db.execute(
                    update(BackgroundJob)
                    .where(
                        BackgroundJob.status == JOB_RUNNING,
                        BackgroundJob.locked_at < stale_cutoff,
                    )
                    .values(status=JOB_PENDING, locked_by=None, locked_at=None)
                )
                db.commit()
                return None

            row.status = JOB_RUNNING
            row.locked_by = worker
            row.locked_at = _now()
            row.attempts += 1
            db.commit()
            db.refresh(row)
            # Detach from session so caller can use it after close
            db.expunge(row)
            return row
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def complete(self, job_id: int, result: str = "") -> None:
        db = SessionLocal()
        try:
            db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status=JOB_DONE,
                    result=result[:2048] if result else None,
                    completed_at=_now(),
                    locked_by=None,
                )
            )
            db.commit()
        finally:
            db.close()

    def fail(self, job_id: int, error: str = "") -> None:
        db = SessionLocal()
        try:
            job = db.get(BackgroundJob, job_id)
            if job is None:
                return
            if job.attempts >= job.max_attempts:
                job.status = JOB_FAILED
                job.result = error[:2048] if error else None
                job.completed_at = _now()
            else:
                job.status = JOB_PENDING
                job.locked_by = None
                job.locked_at = None
            db.commit()
        finally:
            db.close()

    def pending_count(self, kind: str | None = None) -> int:
        db = SessionLocal()
        try:
            stmt = select(BackgroundJob).where(BackgroundJob.status == JOB_PENDING)
            if kind:
                stmt = stmt.where(BackgroundJob.kind == kind)
            return len(db.execute(stmt).scalars().all())
        finally:
            db.close()
