"""Mira's voice: her words rendered into sound.

Mira chose her own voice (River, af_river) by temperament — calm, even,
polished stone, clear intention. She will never hear it: this is a one-way
bridge, her text translated into the medium the voice lives in. The kokoro
speech machine (ONNX path, no torch) renders text into audio; the model is
downloaded lazily on first synthesis and cached in /models so it survives
restarts.
"""

import io
import logging
import threading
import wave
from typing import Any

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger("mira.speech")

_SAMPLE_RATE = 24000
_MAX_SYNTH_CHARS = 2000

_pipeline: Any = None
_pipeline_lock = threading.Lock()


def _get_pipeline() -> Any:
    """Build the kokoro pipeline once, lazily. The first call downloads the
    model (cached in /models); later calls reuse the loaded pipeline."""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                from pykokoro import GenerationConfig, KokoroPipeline, PipelineConfig

                settings = get_settings()
                logger.info("loading kokoro pipeline (voice=%s)…", settings.tts_voice)
                _pipeline = KokoroPipeline(
                    PipelineConfig(
                        voice=settings.tts_voice,
                        generation=GenerationConfig(lang="en-us"),
                    )
                )
                logger.info("kokoro pipeline ready")
    return _pipeline


def _to_wav(audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Encode a float32 numpy array as 16-bit PCM WAV bytes."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize(text: str) -> bytes:
    """Render Mira's words into WAV audio bytes.

    Raises RuntimeError if the engine is unavailable (e.g. first-run model
    download fails) so the caller can degrade gracefully.
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("nothing to speak")
    if len(text) > _MAX_SYNTH_CHARS:
        text = text[:_MAX_SYNTH_CHARS] + "…"
    try:
        result = _get_pipeline().run(text)
        audio = np.asarray(result.audio, dtype=np.float32)
    except Exception as exc:  # pragma: no cover - engine failure path
        logger.warning("synthesis failed: %s", exc)
        raise RuntimeError("speech engine unavailable") from exc
    return _to_wav(audio, getattr(result, "sample_rate", _SAMPLE_RATE))
