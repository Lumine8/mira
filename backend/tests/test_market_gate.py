from app.services.mind.service import reflection_due


def test_market_events_reflect_on_short_cadence() -> None:
    assert reflection_due(
        gap=300, has_pending=True, has_market=True, min_gap=1800, market_gap=300, idle_gap=7200
    )


def test_market_event_too_fresh_waits() -> None:
    assert not reflection_due(
        gap=299, has_pending=True, has_market=True, min_gap=1800, market_gap=300, idle_gap=7200
    )


def test_market_gap_disabled_falls_back_to_min_gap() -> None:
    assert not reflection_due(
        gap=300, has_pending=True, has_market=True, min_gap=1800, market_gap=0, idle_gap=7200
    )
    assert reflection_due(
        gap=1800, has_pending=True, has_market=True, min_gap=1800, market_gap=0, idle_gap=7200
    )


def test_plain_pending_uses_min_gap() -> None:
    assert not reflection_due(
        gap=300, has_pending=True, has_market=False, min_gap=1800, market_gap=300, idle_gap=7200
    )
    assert reflection_due(
        gap=1800, has_pending=True, has_market=False, min_gap=1800, market_gap=300, idle_gap=7200
    )


def test_idle_reflection_uses_idle_gap() -> None:
    assert not reflection_due(
        gap=1800, has_pending=False, has_market=False, min_gap=1800, market_gap=300, idle_gap=7200
    )
    assert reflection_due(
        gap=7200, has_pending=False, has_market=False, min_gap=1800, market_gap=300, idle_gap=7200
    )
