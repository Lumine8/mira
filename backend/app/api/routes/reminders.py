"""The held calendar: reminders, tasks, and events Mira keeps for the voice."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import ReminderIn, ReminderOut
from app.services.identity import get_current_user_id
from app.services.reminders.service import ReminderService

router = APIRouter(prefix="/mira/reminders", tags=["reminders"])


@router.get("", response_model=list[ReminderOut])
def list_reminders(
    include_done: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list:
    """What Mira is holding for the voice right now — open reminders, tasks,
    and events, soonest due first."""
    return ReminderService(db, user_id=user_id).list(include_done=include_done)


@router.post("", response_model=ReminderOut, status_code=201)
def create_reminder(
    body: ReminderIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> object:
    """Ask Mira to hold something: a reminder, a task, or a calendar event."""
    svc = ReminderService(db, user_id=user_id)
    return svc.create(
        title=body.title,
        kind=body.kind,
        due_at=body.due_at,
        note=body.note,
    )


@router.post("/{reminder_id}/done", response_model=ReminderOut)
def done_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> object:
    """Mark a held thing done — the loop never fires it again."""
    item = ReminderService(db, user_id=user_id).mark_done(reminder_id)
    if item is None:
        raise HTTPException(status_code=404, detail="no such reminder")
    return item


@router.delete("/{reminder_id}", status_code=204)
def delete_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> None:
    """Let a held thing go entirely."""
    if not ReminderService(db, user_id=user_id).delete(reminder_id):
        raise HTTPException(status_code=404, detail="no such reminder")