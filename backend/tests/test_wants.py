from app.services.wants.service import (
    next_after_decay,
    normalize_want_text,
    reinforce,
    wants_match,
)


def test_normalize_whitespace_and_case() -> None:
    assert normalize_want_text("  Watch  the Rain ") == "watch the rain"
    assert normalize_want_text("Watch\nthe   rain") == "watch the rain"


def test_wants_match_exact() -> None:
    assert wants_match("to understand how stories stay with people", "to understand how stories stay with people")
    assert wants_match("  Watch the rain.  ", "watch the rain")


def test_wants_match_contains() -> None:
    assert wants_match("understand how stories stay with people", "to understand how stories stay with people forever")
    assert not wants_match("watch the rain", "read a novel")


def test_wants_match_short_phrases_not_merged() -> None:
    # Too short to be safely merged by containment ("rain" vs "drain").
    assert not wants_match("rain", "drain")


def test_decay_lowers_intensity_and_builds_tension() -> None:
    intensity, tension = next_after_decay(80, 10, hours=3.0)
    assert intensity == 74
    assert tension == 16


def test_decay_capped_hours() -> None:
    intensity, tension = next_after_decay(100, 0, hours=9999)
    # hours capped at 6 → -12 / +12
    assert intensity == 88
    assert tension == 12


def test_decay_never_negative() -> None:
    intensity, tension = next_after_decay(5, 100, hours=10)
    assert intensity >= 0
    assert tension <= 100


def test_reinforce_strengthens_toward_stated_strength_and_relieves() -> None:
    intensity, tension = reinforce(intensity=40, tension=50, strength=70)
    assert intensity == 80
    assert tension == 30


def test_reinforce_caps_at_100() -> None:
    intensity, tension = reinforce(intensity=95, tension=0, strength=100)
    assert intensity == 100
    assert tension == 0
