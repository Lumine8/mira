from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.services.identity import get_current_user_id
from app.services.speech.stt import transcribe

router = APIRouter(prefix="/speech", tags=["speech"])


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