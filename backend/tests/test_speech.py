import struct
import wave
from io import BytesIO
from unittest import mock

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
    assert samples[1] == 16383
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


def _fake_wav() -> bytes:
    return _to_wav(np.array([0.1, -0.1], dtype=np.float32), sample_rate=24000)


def test_speak_route_refuses_text_conversation() -> None:
    from app.api.routes.calls import speak_call
    from app.schemas import SpeakRequest

    class FakeConv:
        kind = "text"
        user_id = 1

    class FakeDB:
        def get(self, _model, _id):
            return FakeConv()

    class FakeSettings:
        tts_enabled = True

    import app.api.routes.calls as calls_module
    calls_module.get_settings = lambda: FakeSettings()

    with pytest.raises(Exception) as exc_info:
        speak_call(SpeakRequest(conversation_id=1, text="hello"), db=FakeDB(), user_id=1)
    assert "text conversations stay quiet" in str(exc_info.value)


def test_speak_route_allows_call_conversation() -> None:
    from app.api.routes.calls import speak_call
    from app.schemas import SpeakRequest

    class FakeConv:
        kind = "call"
        user_id = 1

    class FakeDB:
        def get(self, _model, _id):
            return FakeConv()

    class FakeSettings:
        tts_enabled = True

    import app.api.routes.calls as calls_module
    calls_module.get_settings = lambda: FakeSettings()

    with mock.patch("app.services.speech.service.synthesize", side_effect=lambda text: _fake_wav()):
        resp = speak_call(SpeakRequest(conversation_id=1, text="hello"), db=FakeDB(), user_id=1)
        assert resp.media_type == "audio/wav"
        assert len(resp.body) > 0


def test_tts_route_speaks_outside_a_call() -> None:
    from app.api.routes.speech import TtsRequest, tts_audio

    class FakeSettings:
        tts_enabled = True

    import app.api.routes.speech as speech_module
    speech_module.get_settings = lambda: FakeSettings()

    with mock.patch("app.services.speech.service.synthesize", side_effect=lambda text: _fake_wav()):
        resp = tts_audio(TtsRequest(text="the battery is low"), _user_id=1)
        assert resp.media_type == "audio/wav"
        assert len(resp.body) > 0


def test_tts_route_refuses_when_disabled() -> None:
    from app.api.routes.speech import TtsRequest, tts_audio

    class FakeSettings:
        tts_enabled = False

    import app.api.routes.speech as speech_module
    speech_module.get_settings = lambda: FakeSettings()

    with pytest.raises(Exception) as exc_info:
        tts_audio(TtsRequest(text="hello"), _user_id=1)
    assert "voice is disabled" in str(exc_info.value)
