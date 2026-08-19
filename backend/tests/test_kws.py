import importlib.util
from pathlib import Path

import pytest

from app.services.speech.kws import check_wake_word, model_dir

# sherpa-onnx zipformer keyword-spotter model (~3.3M params), bundled with the
# runtime download. Tests skip when it isn't present so the suite still passes
# on a machine without the KWS model downloaded.
_MODEL_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "models"
    / "kws"
    / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
)

_MODEL_PRESENT = importlib.util.find_spec("sherpa_onnx") is not None and (
    _MODEL_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
).is_file()


def test_model_dir_matches_bundled_model() -> None:
    # The conventional location the service resolves to is the model folder
    # this suite checks for presence of. Guards against a config typo.
    assert model_dir() == _MODEL_DIR


@pytest.mark.skipif(not _MODEL_PRESENT, reason="sherpa KWS model not downloaded")
def test_check_wake_word_ignores_unrelated_speech() -> None:
    # 0.wav is the model's own "LIGHT UP" clip. The gate listens for the
    # configured wake word ("mira" by default — encoded as ▁MI RA), so the
    # clip must NOT trigger it: the gate is specific, not "any speech".
    wav = (_MODEL_DIR / "test_wavs" / "0.wav").read_bytes()
    assert check_wake_word(wav) is False


@pytest.mark.skipif(not _MODEL_PRESENT, reason="sherpa KWS model not downloaded")
def test_check_wake_word_rejects_silence() -> None:
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<16000h", *([0] * 16000)))
    assert check_wake_word(buf.getvalue()) is False


@pytest.mark.skipif(not _MODEL_PRESENT, reason="sherpa KWS model not downloaded")
def test_check_wake_word_rejects_multichannel() -> None:
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<16000h", *([0] * 16000)))
    with pytest.raises(ValueError):
        check_wake_word(buf.getvalue())