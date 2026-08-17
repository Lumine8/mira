import importlib.util
from pathlib import Path

import pytest

from app.services.speech.stt import transcribe

# sherpa-onnx whisper base.en model, bundled with the runtime download. The
# test is skipped when the model isn't present so the suite still passes on a
# machine without the (large) STT model downloaded.
_MODEL_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "models"
    / "sherpa"
    / "sherpa-onnx-whisper-base.en"
)

_MODEL_PRESENT = importlib.util.find_spec("sherpa_onnx") is not None and (
    _MODEL_DIR / "base.en-encoder.int8.onnx"
).is_file()


@pytest.mark.skipif(not _MODEL_PRESENT, reason="sherpa whisper model not downloaded")
def test_transcribe_bundled_wav() -> None:
    wav = (_MODEL_DIR / "test_wavs" / "0.wav").read_bytes()
    text = transcribe(wav)
    assert "nightfall" in text.lower() or "brothels" in text.lower()


@pytest.mark.skipif(not _MODEL_PRESENT, reason="sherpa whisper model not downloaded")
def test_transcribe_silence_is_empty() -> None:
    import struct
    import wave
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<8000h", *([0] * 8000)))
    assert transcribe(buf.getvalue()) == ""


@pytest.mark.skipif(not _MODEL_PRESENT, reason="sherpa whisper model not downloaded")
def test_transcribe_rejects_multichannel() -> None:
    import struct
    import wave
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<16000h", *([0] * 16000)))
    with pytest.raises(ValueError):
        transcribe(buf.getvalue())