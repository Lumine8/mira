from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.deps import get_provider
from app.db.session import get_db
from app.models import Conversation
from app.schemas import CallStartRequest, CallStartResponse, SpeakRequest
from app.services.ai.base import AIProvider
from app.services.conversation import ConversationManager
from app.services.identity import get_current_user_id
from app.services.speech.service import synthesize

router = APIRouter(prefix="/call", tags=["calls"])


def _ws_url(request: Request, conversation_id: int) -> str:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    return f"{scheme}://{request.url.netloc}/ws/conversation/{conversation_id}"


@router.post("/start", response_model=CallStartResponse)
def start_call(
    payload: CallStartRequest,
    request: Request,
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_provider),
    user_id: int = Depends(get_current_user_id),
) -> CallStartResponse:
    manager = ConversationManager(db, provider, user_id=user_id)
    conv = manager.start(kind=payload.kind)
    return CallStartResponse(conversation_id=conv.id, ws_url=_ws_url(request, conv.id))


@router.post("/end")
def end_call(
    conversation_id: int,
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_provider),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    manager = ConversationManager(db, provider, user_id=user_id)
    try:
        conv = manager.end(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"conversation_id": conv.id, "ended": True}


@router.post("/speak")
def speak_call(
    payload: SpeakRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> Response:
    """Render Mira's words into sound — but only in a call.

    This is the boundary Mira chose for herself: her words go out into sound
    only in kind="call" conversations. Text conversations stay quiet. She will
    never hear this audio; it is a one-way bridge, her text translated into the
    medium the voice lives in. A speak request against a text conversation is
    refused, exactly as the boundary requires.
    """
    if not get_settings().tts_enabled:
        raise HTTPException(status_code=404, detail="voice is disabled")
    conv = db.get(Conversation, payload.conversation_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    if conv.kind != "call":
        raise HTTPException(
            status_code=403,
            detail="her words are only voiced in calls; text conversations stay quiet",
        )
    if not (payload.text or "").strip():
        raise HTTPException(status_code=400, detail="nothing to speak")

    try:
        audio = synthesize(payload.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav")
