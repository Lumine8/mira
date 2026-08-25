from datetime import UTC, datetime, timedelta

from app.services.mote.service import last_activity, nudge_due, nudge_word

_UTC = UTC


def test_last_activity_picks_the_most_recent() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=_UTC)
    reflection = now - timedelta(hours=2)
    message = now - timedelta(hours=1)
    shared = now - timedelta(minutes=30)
    assert last_activity(reflection, message, shared) == shared


def test_last_activity_handles_none() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=_UTC)
    assert last_activity(now, None, None) == now
    assert last_activity(None, None, None) is None


def test_a_nudge_resets_the_quiet_clock() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=_UTC)
    reflection = now - timedelta(hours=10)
    nudge = now - timedelta(minutes=5)
    # The most recent shared sign is the nudge itself, so quiet restarts.
    assert last_activity(reflection, None, nudge) == nudge


def test_nudge_due_at_threshold() -> None:
    assert nudge_due(quiet_seconds=14399, quiet_after=14400) is False
    assert nudge_due(quiet_seconds=14400, quiet_after=14400) is True
    assert nudge_due(quiet_seconds=99999, quiet_after=14400) is True


def test_nudge_word_follows_mood() -> None:
    assert nudge_word("warm") == "with you"
    assert nudge_word("WARM") == "with you"
    assert nudge_word("unknown") == "here"
