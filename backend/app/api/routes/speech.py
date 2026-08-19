from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.identity import get_current_user_id
from app.services.speech.kws import check_wake_word
from app.services.speech.service import synthesize
from app.services.speech.stt import transcribe

router = APIRouter(prefix="/speech", tags=["speech"])


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/tts")
def tts_audio(payload: TtsRequest, _user_id: int = Depends(get_current_user_id)) -> Response:
    """Render text into Mira's voice without requiring a call conversation.

    This is the voice-output bridge for her self-initiated messages (the mind
    loop reaching out on its own), which live in kind="self" conversations and
    are therefore refused by POST /call/speak. The call boundary for replies is
    untouched; this endpoint exists only so her proactive words can be heard.
    """
    if not get_settings().tts_enabled:
        raise HTTPException(status_code=404, detail="voice is disabled")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="nothing to speak")
    try:
        audio = synthesize(text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav")


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    _user_id: int = Depends(get_current_user_id),
) -> dict:
    """Turn spoken audio (mono 16-bit WAV) into text — fully local.

    The HUD records a segment and uploads it here; sherpa-onnx whisper
    transcribes it on this machine. The audio is processed in memory and never
    stored. Empty result just means silence.
    """
    wav = await file.read()
    if not wav:
        raise HTTPException(status_code=400, detail="empty audio")
    try:
        text = transcribe(wav)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"text": text}


@router.post("/wake")
async def wake_word_audio(
    file: UploadFile = File(...),
    _user_id: int = Depends(get_current_user_id),
) -> dict:
    """Did this audio contain the wake word? Cheap audio-level gate.

    The keyword-spotter runs before whisper: in always-listening mode the HUD
    sends each captured segment here first, and only asks for a full
    transcription (POST /speech/transcribe) when her name is actually spoken.
    When no wake word is configured, or the model isn't downloaded, this always
    returns heard=true so behaviour is unchanged.
    """
    wav = await file.read()
    if not wav:
        raise HTTPException(status_code=400, detail="empty audio")
    try:
        heard = check_wake_word(wav)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"heard": heard}