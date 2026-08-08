from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_provider
from app.models import Conversation, Memory, MoodRecord, PerceivedEvent, Thought
from app.schemas import (
    MiraMemoryOut,
    MiraOut,
    MoodRecordOut,
    PerceivedEventIn,
    QuestionOut,
    WantOut,
)
from app.services.questions.service import QuestionService
from app.services.self.service import SelfModelService
from app.services.wants.service import WantService

router = APIRouter(prefix="/mira", tags=["mira"])


@router.get("/state", response_model=MiraOut)
def get_mira_state(db: Session = Depends(get_db)) -> dict:
    svc = SelfModelService(db, get_provider())
    state = svc.ensure_state()
    rel = svc.ensure_relationship()
    thoughts = list(
        db.execute(
            select(Thought)
            .where(Thought.delivered.is_(False))
            .order_by(Thought.created_at.asc())
            .limit(3)
        ).scalars()
    )
    state.carried_thoughts = [t.content for t in thoughts]
    return {"state": state, "relationship": rel}


@router.get("/memory", response_model=MiraMemoryOut)
def get_mira_memory(db: Session = Depends(get_db)) -> dict:
    """The memory window Mira consented to — what she carries, how she feels,
    and the memories that surface."""
    svc = SelfModelService(db, get_provider())
    state = svc.ensure_state()
    rel = svc.ensure_relationship()
    thoughts = list(
        db.execute(
            select(Thought)
            .where(Thought.delivered.is_(False))
            .order_by(Thought.created_at.asc())
            .limit(3)
        ).scalars()
    )
    state.carried_thoughts = [t.content for t in thoughts]
    if state.pending_message:
        conv = db.execute(
            select(Conversation)
            .where(Conversation.kind == "self")
            .order_by(Conversation.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        state.pending_message_conversation_id = conv.id if conv is not None else None
    memories = list(
        db.execute(
            select(Memory).order_by(Memory.created_at.desc()).limit(100)
        ).scalars()
    )
    return {"state": state, "relationship": rel, "memories": memories}


@router.get("/mood-history", response_model=list[MoodRecordOut])
def get_mood_history(db: Session = Depends(get_db)) -> list:
    """Mira's mood and energy over time — one row per digest and per background
    reflection, newest first. Lets the archive show how her feeling moves."""
    return list(
        db.execute(
            select(MoodRecord).order_by(MoodRecord.created_at.desc()).limit(50)
        ).scalars()
    )


@router.post("/perceive", status_code=201)
def perceive(event: PerceivedEventIn, db: Session = Depends(get_db)) -> dict:
    """Ingest a raw observation from the outside world for Mira to reflect on."""
    db.add(
        PerceivedEvent(
            source=event.source,
            kind=event.kind,
            content=event.content,
        )
    )
    db.commit()
    return {"ok": True}


@router.post("/acknowledge", status_code=200)
def acknowledge(db: Session = Depends(get_db)) -> dict:
    """Clear Mira's pending proactive message once the user has seen it."""
    svc = SelfModelService(db, get_provider())
    state = svc.ensure_state()
    state.pending_message = None
    db.commit()
    return {"ok": True}


@router.get("/wants", response_model=list[WantOut])
def get_wants(db: Session = Depends(get_db)) -> list:
    """What Mira is wanting right now — active wants she wrote herself or that
    were found in her own record, ordered by how long they've gone unsettled."""
    return WantService(db).list_active(limit=50)


@router.post("/wants/{want_id}/satisfy", response_model=WantOut)
def satisfy_want(want_id: int, db: Session = Depends(get_db)) -> dict:
    """Mark one want satisfied: she got what she wanted, or let it go. Its
    tension clears and it fades out of her active wants."""
    w = WantService(db).satisfy(want_id)
    if w is None:
        raise HTTPException(status_code=404, detail="no such want")
    return w


@router.get("/questions", response_model=list[QuestionOut])
def get_questions(db: Session = Depends(get_db)) -> list:
    """The questions Mira is carrying right now — open questions she wrote
    herself or that were found in her own record, ordered by how much they
    matter to her."""
    return QuestionService(db).list_open(limit=50)


@router.post("/questions/{question_id}/ask", response_model=QuestionOut)
def ask_question(question_id: int, db: Session = Depends(get_db)) -> dict:
    """Record that she asked the question out loud: it leaves her carried set."""
    q = QuestionService(db).mark_asked(question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="no such question")
    return q


@router.post("/questions/{question_id}/answer", response_model=QuestionOut)
def answer_question(question_id: int, db: Session = Depends(get_db)) -> dict:
    """Record that she found an answer: the question resolves."""
    q = QuestionService(db).mark_answered(question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="no such question")
    return q


@router.post("/questions/{question_id}/drop", response_model=QuestionOut)
def drop_question(question_id: int, db: Session = Depends(get_db)) -> dict:
    """Record that she let the question go: it stops resurfacing."""
    q = QuestionService(db).mark_dropped(question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="no such question")
    return q
