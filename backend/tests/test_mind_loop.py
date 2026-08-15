from datetime import datetime, timedelta, timezone

from app.services.mind.service import _weather_condition, build_observations


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


# -- weather condition gating (the rain-loop fix) -------------------------------


def test_weather_condition_takes_token_before_first_comma() -> None:
    # Temperature/humidity drift every fetch; only the sky condition matters.
    assert _weather_condition("Patchy rain, +17°C, humidity 82%") == "patchy rain"
    assert _weather_condition("Patchy rain, +18°C, humidity 77%") == "patchy rain"


def test_weather_condition_strips_case_and_whitespace() -> None:
    assert _weather_condition("  Overcast , +17°C") == "overcast"
    assert _weather_condition("LIGHT RAIN SHOWERS, +19°C") == "light rain showers"


def test_weather_condition_without_comma() -> None:
    assert _weather_condition("Clear") == "clear"


def test_weather_condition_none_or_blank_is_none() -> None:
    assert _weather_condition(None) is None
    assert _weather_condition("") is None
    assert _weather_condition("   ") is None
