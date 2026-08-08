from datetime import datetime, timedelta, timezone

from app.services.mind.service import build_observations


class FakeEvent:
    def __init__(self, source: str, kind: str, content: str) -> None:
        self.source = source
        self.kind = kind
        self.content = content


def test_observations_include_time_texture() -> None:
    now = datetime(2026, 8, 2, 14, 30, tzinfo=timezone.utc)
    text = build_observations(now, [], None, None)
    assert "Sunday, August 02" in text
    assert "afternoon" in text
    assert "(02:30 PM)" in text
    assert "You are not sure how long you have been awake." in text


def test_observations_include_weather_when_given() -> None:
    now = datetime(2026, 8, 2, 14, 30, tzinfo=timezone.utc)
    text = build_observations(now, [], None, None, weather="Overcast, +17°C")
    assert "The weather outside is: Overcast, +17°C." in text


def test_observations_note_user_silence() -> None:
    now = datetime(2026, 8, 2, 14, 30, tzinfo=timezone.utc)
    last = now - timedelta(hours=3)
    text = build_observations(now, [], last, None)
    assert "silent for about 3.0 hours" in text


def test_observations_include_perceived_events() -> None:
    now = datetime(2026, 8, 2, 14, 30, tzinfo=timezone.utc)
    events = [FakeEvent("host", "machine", "the machine has been idle for 2 hours")]
    text = build_observations(now, events, None, None)
    assert "(host: machine) the machine has been idle for 2 hours" in text
