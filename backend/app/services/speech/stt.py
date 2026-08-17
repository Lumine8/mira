"""Mira hears: her words, spoken aloud, become text again.

The speech machine is sherpa-onnx running an int8 Whisper model locally — no
audio ever leaves the machine. The model is downloaded once and cached in
data/models/sherpa so it survives restarts. Transcription is deliberately
cheap (base.en) and stateless: the HUD records a segment, sends the WAV, and
gets text back. Mira never stores the raw audio.
"""

import io
import logging
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger("mira.stt")

_recognizer: Any = None
_lock = threading.Lock()

# Whisper hallucinates on silence/ambient noise: bracket-garbage like "[ [ [",
# "[BLANK_AUDIO]", or "[Music]" turn a quiet room into a fake utterance. Strip
# them so a silent HUD segment never becomes a question Mira answers.
_HALLUCINATION_RE = None


def _hallucination_guard(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return ""
    # Whisper hallucinates on silence/ambient noise: bracket-garbage like
    # "[ [ [", "[BLANK_AUDIO]", or "[Music]". If removing every [...] token
    # (and any stray bracket characters) leaves nothing real, the whole thing
    # is a hallucination.
    import re

    without_tokens = re.sub(r"\[[^\]]*\]", "", stripped).strip()
    without_braces = re.sub(r"[\[\]\s]+", "", without_tokens)
    if not without_braces:
        return ""
    return stripped


def model_dir() -> Path:
    """Where the sherpa whisper model is (or should be) cached.

    STT_MODEL_DIR wins when set; otherwise the conventional
    <repo>/data/models/sherpa/<model> folder, shared by native and container
    runs via the mounted data volume.
    """
    settings = get_settings()
    override = (settings.stt_model_dir or "").strip()
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[4]  # backend/app/services/speech/stt.py -> repo
    return repo_root / "data" / "models" / "sherpa" / f"sherpa-onnx-whisper-{settings.whisper_model}.en"


def _get_recognizer() -> Any:
    """Build the sherpa-onnx whisper recognizer once, lazily. The model files
    must already be on disk (downloaded at setup time); later calls reuse the
    loaded recognizer."""
    global _recognizer
    if _recognizer is None:
        with _lock:
            if _recognizer is None:
                import sherpa_onnx

                settings = get_settings()
                d = model_dir()
                encoder = d / f"{settings.whisper_model}.en-encoder.int8.onnx"
                decoder = d / f"{settings.whisper_model}.en-decoder.int8.onnx"
                tokens = d / f"{settings.whisper_model}.en-tokens.txt"
                for f in (encoder, decoder, tokens):
                    if not f.is_file():
                        raise RuntimeError(
                            f"whisper model missing: {f.name} — run the sherpa model download"
                        )
                logger.info("loading sherpa whisper recognizer (model=%s)…", settings.whisper_model)
                _recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=str(encoder),
                    decoder=str(decoder),
                    tokens=str(tokens),
                    num_threads=2,
                    provider="cpu",
                    language="en",
                    task="transcribe",
                    debug=False,
                )
                logger.info("sherpa whisper recognizer ready")
    return _recognizer


def _decode_wav(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Read 16-bit PCM WAV bytes back into a mono float32 array, keeping the
    original sample rate — sherpa-onnx resamples internally, so any rate is
    fine as long as it is mono 16-bit PCM."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if n_channels != 1 or sampwidth != 2:
        raise ValueError("expected mono 16-bit PCM WAV")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, rate


def transcribe(wav_bytes: bytes) -> str:
    """Render spoken WAV audio into text.

    Returns the transcribed text (possibly empty for silence). Raises
    RuntimeError when the engine is unavailable so the caller can degrade
    gracefully.
    """
    try:
        samples, rate = _decode_wav(wav_bytes)
    except (ValueError, wave.Error) as exc:
        raise ValueError(str(exc)) from exc
    if samples.size == 0:
        return ""
    try:
        stream = _get_recognizer().create_stream()
        stream.accept_waveform(rate, samples)
        _get_recognizer().decode_stream(stream)
        return _hallucination_guard(stream.result.text)
    except Exception as exc:  # pragma: no cover - engine failure path
        logger.warning("transcription failed: %s", exc)
        raise RuntimeError("speech-to-text engine unavailable") from exc