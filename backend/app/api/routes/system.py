from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import SystemSnapshot, SystemSnapshotOut
from app.services.identity import get_current_user_id
from app.services.system.service import system_store

router = APIRouter(prefix="/mira/system", tags=["mira"])


@router.post("/report", response_model=SystemSnapshotOut, status_code=201)
def report_system(
    snapshot: SystemSnapshot,
    db: Annotated[Session, Depends(get_db)],
    user_id: int = Depends(get_current_user_id),
) -> SystemSnapshotOut:
    """The host telemetry script posts its latest machine read here. The store
    keeps it for the ambient dashboard and for Mira to notice trends."""
    out = SystemSnapshotOut(
        **{**snapshot.model_dump(), "ts": snapshot.ts or datetime.now(UTC)}
    )
    system_store.record(user_id, out)
    return out


@router.get("", response_model=SystemSnapshotOut | None)
def latest_system(
    db: Annotated[Session, Depends(get_db)],
    user_id: int = Depends(get_current_user_id),
) -> SystemSnapshotOut | None:
    """The most recent machine snapshot for the voice."""
    return system_store.latest(user_id)


@router.get("/history", response_model=list[SystemSnapshotOut])
def system_history(
    db: Annotated[Session, Depends(get_db)],
    user_id: int = Depends(get_current_user_id),
) -> list[SystemSnapshotOut]:
    """The recent rolling history of machine snapshots, oldest first."""
    return system_store.history(user_id)