"""Mira's ears, second pass: she hears her name before she has to listen.

The voice is transcribed by whisper, but whisper is heavy — running it on every
utterance in always-listening mode burns CPU on chatter nobody asked her to
answer. So a tiny keyword-spotter model (sherpa-onnx zipformer KWS, ~3.3M
params) listens first: when the configured wake word is spoken, the HUD runs
the real transcription; otherwise the utterance is dropped cheaply.

The spotter is loaded once and reused. The wake word is configurable, so it is
BPE-tokenized at load time (the model's vocabulary is a sentencepiece model)
and written to a temporary keywords file the spotter constructor reads.
"""

import io
import logging
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger("mira.kws")

_spotter: Any = None
_lock = threading.Lock()
_loaded_wake_word: str | None = None


def model_dir() -> Path:
    """Where the keyword-spotter model lives (or should live).

    KWS_MODEL_DIR wins when set; otherwise the conventional
    <repo>/data/models/kws/<model> folder, shared by native and container runs
    via the mounted data volume — same rule as the whisper model.
    """
    settings = get_settings()
    override = (settings.kws_model_dir or "").strip()
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[4]  # backend/app/services/speech/kws.py -> repo
    return repo_root / "data" / "models" / "kws" / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"


def _keyword_line(wake_word: str) -> str:
    """BPE-encode the wake word into the tokens.txt vocabulary.

    sentencepiece encodes "mira" as ["M", "I", "RA"]-style pieces; the model's
    vocabulary stores them in uppercase form (▁MI RA), so uppercase before
    encoding. Returns the keyword line, or None when the word can't be encoded
    (out-of-vocabulary pieces) — the caller then falls back to no gating.
    """
    import io
    import sys

    from sherpa_onnx.utils import text2token

    d = model_dir()
    # text2token prints "Can't find token …" warnings (containing non-ASCII
    # piece markers) to stdout for out-of-vocabulary words. Silence them so a
    # cp1252 console doesn't explode on encode.
    original_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        encoded = text2token(
            [wake_word.upper()],
            str(d / "tokens.txt"),
            tokens_type="bpe",
            bpe_model=str(d / "bpe.model"),
        )
    finally:
        sys.stdout = original_stdout
    if not encoded or not encoded[0]:
        return None
    return " ".join(encoded[0])


def _build_spotter(wake_word: str) -> Any:
    """Load the sherpa KeywordSpotter for the given wake word. Only keywords
    the user configured are in the file, so any detection is a summon."""
    global _spotter, _loaded_wake_word
    if _spotter is not None and _loaded_wake_word == wake_word:
        return _spotter
    if _spotter is not None:
        logger.info("wake word changed (%r -> %r); rebuilding spotter", _loaded_wake_word, wake_word)
    import sherpa_onnx

    d = model_dir()
    encoder = d / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
    decoder = d / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
    joiner = d / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
    for f in (encoder, decoder, joiner):
        if not f.is_file():
            raise RuntimeError(f"KWS model missing: {f.name} — run the sherpa KWS model download")

    line = _keyword_line(wake_word)
    if not line:
        logger.warning("wake word %r is not in the KWS vocabulary; disabling audio gate", wake_word)
        _spotter = None
        _loaded_wake_word = wake_word
        return None

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as kws_file:
        kws_file.write(f"{line}\n")
        kws_path = kws_file.name

    settings = get_settings()
    logger.info("loading sherpa keyword spotter (wake word=%r)…", wake_word)
    _spotter = sherpa_onnx.KeywordSpotter(
        tokens=str(d / "tokens.txt"),
        encoder=str(encoder),
        decoder=str(decoder),
        joiner=str(joiner),
        keywords_file=kws_path,
        sample_rate=16000,
        feature_dim=80,
        keywords_score=settings.kws_score,
        keywords_threshold=settings.kws_threshold,
    )
    _loaded_wake_word = wake_word
    logger.info("sherpa keyword spotter ready")
    return _spotter


def _get_spotter() -> Any:
    """Build the spotter once per wake word, lazily, under a lock."""
    wake_word = (get_settings().wake_word or "").strip()
    if not wake_word:
        return None
    global _spotter
    if _spotter is None or _loaded_wake_word != wake_word:
        with _lock:
            if _spotter is None or _loaded_wake_word != wake_word:
                try:
                    _build_spotter(wake_word)
                except RuntimeError as exc:
                    logger.warning("keyword spotter unavailable: %s", exc)
                    _spotter = None
    return _spotter


def _decode_wav(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Read 16-bit PCM WAV bytes into a mono float32 array. Same contract as
    stt: mono 16-bit PCM at any sample rate; sherpa resamples internally."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if n_channels != 1 or sampwidth != 2:
        raise ValueError("expected mono 16-bit PCM WAV")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, rate


def check_wake_word(wav_bytes: bytes) -> bool:
    """True when the audio contains the configured wake word.

    False when the wake word isn't configured, when the model is missing, or
    when the word can't be encoded — i.e. the caller should not gate on it.
    Raises ValueError for malformed WAV input.
    """
    spotter = _get_spotter()
    if spotter is None:
        return True  # no gate configured / unavailable -> always proceed
    try:
        samples, rate = _decode_wav(wav_bytes)
    except (ValueError, wave.Error) as exc:
        raise ValueError(str(exc)) from exc
    if samples.size == 0:
        return False

    stream = spotter.create_stream()
    stream.accept_waveform(rate, samples)
    # Tail padding: the model only emits a detection once it has seen enough
    # audio after the keyword, so append silence to flush the decision out.
    # Must be fed at the same sample rate as the audio or sherpa refuses.
    tail_paddings = np.zeros(int(0.66 * rate), dtype=np.float32)
    stream.accept_waveform(rate, tail_paddings)
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        if spotter.get_result(stream):
            return True
    return False