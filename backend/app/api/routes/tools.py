from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import PendingChangeOut, ProposeChangeIn
from app.services.tools import ToolError, ToolService

router = APIRouter(prefix="/mira/tools", tags=["mira"])


class HostResultIn(BaseModel):
    result: str = Field(min_length=1, max_length=8000)


@router.get("/pending", response_model=list[PendingChangeOut])
def list_pending(db: Session = Depends(get_db)) -> list:
    return ToolService(db).list_pending()


@router.get("/history", response_model=list[PendingChangeOut])
def list_history(limit: int = 25, db: Session = Depends(get_db)) -> list:
    """Everything Mira has modified or proposed, newest first — the record of
    what she changes about herself. Browsing is always in here too."""
    return ToolService(db).history(limit=limit)


@router.post("/propose", response_model=PendingChangeOut, status_code=201)
def propose(change: ProposeChangeIn, db: Session = Depends(get_db)) -> PendingChangeOut:
    try:
        return ToolService(db).propose_change(change.kind, change.summary, change.payload)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/approve/{change_id}", response_model=PendingChangeOut)
def approve(change_id: int, db: Session = Depends(get_db)) -> PendingChangeOut:
    try:
        return ToolService(db).approve(change_id)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/deny/{change_id}", response_model=PendingChangeOut)
def deny(change_id: int, db: Session = Depends(get_db)) -> PendingChangeOut:
    try:
        return ToolService(db).deny(change_id)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/host-pending", response_model=list[PendingChangeOut])
def host_pending(db: Session = Depends(get_db)) -> list:
    """Approved host commands waiting for the host agent to run them."""
    return ToolService(db).host_pending()


@router.post("/host-result/{change_id}", response_model=PendingChangeOut)
def host_result(change_id: int, body: HostResultIn, db: Session = Depends(get_db)) -> PendingChangeOut:
    """The host agent reports what an approved command returned."""
    try:
        return ToolService(db).apply_host_result(change_id, body.result)
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
