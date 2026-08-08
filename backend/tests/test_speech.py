import struct
import wave
from io import BytesIO

import numpy as np
import pytest

from app.services.speech.service import _to_wav


def test_to_wav_encodes_pcm16_mono() -> None:
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    data = _to_wav(audio, sample_rate=24000)

    with wave.open(BytesIO(data), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000
        frames = wav.readframes(wav.getnframes())
    samples = struct.unpack("<%dh" % (len(frames) // 2), frames)
    assert samples[0] == 0
    assert samples[1] == 16383  # 0.5 * 32767, truncated by int16 cast
    assert samples[2] == -16383
    assert samples[3] == 32767
    assert samples[4] == -32767


def test_to_wav_clips_out_of_range() -> None:
    audio = np.array([2.0, -2.0], dtype=np.float32)
    data = _to_wav(audio, sample_rate=24000)
    with wave.open(BytesIO(data), "rb") as wav:
        frames = wav.readframes(2)
    samples = struct.unpack("<2h", frames)
    assert samples == (32767, -32767)


def test_speak_route_refuses_text_conversation() -> None:
    """Her boundary: words are voiced only in calls. A text conversation must be
    refused, whatever the payload."""
    from app.api.routes.calls import speak_call
    from app.schemas import SpeakRequest

    class FakeConv:
        kind = "text"

    class FakeDB:
        def get(self, _model, _id):
            return FakeConv()

    class FakeSettings:
        tts_enabled = True

    import app.api.routes.calls as calls_module

    calls_module.get_settings = lambda: FakeSettings()

    with pytest.raises(Exception) as exc_info:
        speak_call(SpeakRequest(conversation_id=1, text="hello"), db=FakeDB())
    assert "text conversations stay quiet" in str(exc_info.value)


def test_speak_route_allows_call_conversation() -> None:
    """A call conversation should proceed to synthesis (which we stub)."""
    import app.api.routes.calls as calls_module
    from app.schemas import SpeakRequest

    class FakeConv:
        kind = "call"

    class FakeDB:
        def get(self, _model, _id):
            return FakeConv()

    class FakeSettings:
        tts_enabled = True

    calls_module.get_settings = lambda: FakeSettings()

    original = calls_module.synthesize
    calls_module.synthesize = lambda text: _to_wav(
        np.array([0.1, -0.1], dtype=np.float32), sample_rate=24000
    )
    try:
        resp = calls_module.speak_call(SpeakRequest(conversation_id=1, text="hello"), db=FakeDB())
        assert resp.media_type == "audio/wav"
        assert len(resp.body) > 0
    finally:
        calls_module.synthesize = original
