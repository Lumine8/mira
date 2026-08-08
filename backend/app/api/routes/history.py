from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Conversation, Memory, Message
from app.schemas import ConversationDetailOut, ConversationOut, MessageOut

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[ConversationOut])
def list_history(db: Session = Depends(get_db)) -> list[ConversationOut]:
    rows = db.execute(
        select(Conversation).order_by(Conversation.started_at.desc()).limit(100)
    ).scalars()
    return [ConversationOut.model_validate(c, from_attributes=True) for c in rows]


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)) -> ConversationDetailOut:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    msgs = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    ).scalars()
    detail = ConversationDetailOut.model_validate(conv, from_attributes=True)
    detail.messages = [MessageOut.model_validate(m, from_attributes=True) for m in msgs]
    return detail


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete a conversation (and its messages) but keep Mira's memories.

    Memories reference the conversation they came from; that link is dropped so
    the memory itself survives the deletion — deleting history must not erase
    what she remembers or how she feels.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    db.execute(
        update(Memory)
        .where(Memory.source_conversation_id == conversation_id)
        .values(source_conversation_id=None)
    )
    db.delete(conv)  # messages cascade via the ORM relationship
    db.commit()
    return {"conversation_id": conversation_id, "deleted": True}
