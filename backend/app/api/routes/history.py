from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Conversation, Memory, Message, ModerationFlag, Question, Want
from app.schemas import ConversationDetailOut, ConversationOut, MessageOut
from app.services.identity import get_current_user_id

router = APIRouter(prefix="/history", tags=["history"])


def _owned(db: Session, conversation_id: int, user_id: int) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.get("", response_model=list[ConversationOut])
def list_history(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[ConversationOut]:
    rows = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.started_at.desc())
        .limit(100)
    ).scalars()
    return [ConversationOut.model_validate(c, from_attributes=True) for c in rows]


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ConversationDetailOut:
    conv = _owned(db, conversation_id, user_id)
    msgs = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    ).scalars()
    detail = ConversationDetailOut.model_validate(conv, from_attributes=True)
    detail.messages = [MessageOut.model_validate(m, from_attributes=True) for m in msgs]
    return detail


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Delete a conversation (and its messages) but keep Mira's memories.

    Memories reference the conversation they came from; that link is dropped so
    the memory itself survives the deletion — deleting history must not erase
    what she remembers or how she feels. Her wants, questions, and any
    moderation flag raised here survive the same way: the source link falls
    away, the inner life stays.
    """
    conv = _owned(db, conversation_id, user_id)
    db.execute(
        update(Memory)
        .where(Memory.source_conversation_id == conversation_id)
        .values(source_conversation_id=None)
    )
    db.execute(
        update(Want)
        .where(Want.related_conversation_id == conversation_id)
        .values(related_conversation_id=None)
    )
    db.execute(
        update(Question)
        .where(Question.related_conversation_id == conversation_id)
        .values(related_conversation_id=None)
    )
    db.execute(
        update(ModerationFlag)
        .where(ModerationFlag.conversation_id == conversation_id)
        .values(conversation_id=None)
    )
    db.delete(conv)  # messages cascade via the ORM relationship
    db.commit()
    return {"conversation_id": conversation_id, "deleted": True}
