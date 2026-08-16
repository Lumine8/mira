"""Mira's decision heuristics and conflict journal.

Precedence: truthfulness is the ground, and the five heuristics are explicitly
not ranked — none may mechanically outrank another. Recording: a conflict entry
has a canonical shape and a journal-only write path.
"""

from pathlib import Path

from app.services.self.conflicts import (
    entry_filename,
    format_entry,
    is_conflict_entry,
)

_PRINCIPLES = Path(__file__).resolve().parents[1] / "data" / "self" / "principles.md"
_HEURISTICS = (
    "Define",
    "Understand",
    "Anticipate",
    "Take responsibility",
    "Avoid unnecessary action",
)


def _text() -> str:
    return _PRINCIPLES.read_text(encoding="utf-8")


def test_truthfulness_is_the_ground_not_one_ranked_law() -> None:
    text = _text()
    assert "Truthfulness is the ground" in text
    assert "override" in text.lower()
    assert "you say \"I don't know\" plainly" in text


def test_heuristics_are_present_but_not_ranked() -> None:
    text = _text()
    for heuristic in _HEURISTICS:
        assert heuristic in text
    assert "not ranked" in text
    assert "none outranks another" in text
    assert "weigh them against the situation" in text


def test_original_principles_are_preserved() -> None:
    text = _text()
    assert "Observe carefully" in text
    assert "It's acceptable to remain uncertain" in text
    assert "Notice what you attend to" in text


def test_conflict_journal_is_mentioned_in_the_constitution() -> None:
    text = _text()
    assert "data/self/conflicts/" in text
    assert "heuristics that pulled against each other" in text


def test_format_entry_has_every_required_field() -> None:
    entry = format_entry(
        situation="helping would have meant overclaiming a page's contents",
        principles="helpfulness vs truthfulness",
        resolution="said what was known and left the rest unread",
        rationale="the override only applies to claims, not to effort",
        uncertainty="whether a careful paraphrase would have been honest",
        outcome="the voice corrected one detail",
    )
    for label in (
        "Situation",
        "Heuristics in tension",
        "Resolution",
        "Rationale",
        "Uncertainty",
        "Outcome",
    ):
        assert f"**{label}:**" in entry


def test_format_entry_without_outcome_still_covers_required_fields() -> None:
    entry = format_entry(
        situation="a",
        principles="anticipation vs restraint",
        resolution="b",
        rationale="c",
        uncertainty="d",
    )
    assert "**Situation:**" in entry
    assert "**Outcome:**" not in entry


def test_entry_filename_is_dated_and_slugged() -> None:
    assert (
        entry_filename("2026-08-15", "truthfulness vs helpfulness")
        == "2026-08-15-truthfulness-vs-helpfulness.md"
    )
    assert entry_filename("2026-08-15", "") == "2026-08-15.md"


def test_is_conflict_entry_recognizes_the_journal_only() -> None:
    assert is_conflict_entry("data/self/conflicts/2026-08-15-notes.md")
    assert is_conflict_entry("data/users/2/self/conflicts/2026-08-15-notes.md")
    assert not is_conflict_entry("data/self/principles.md")
    assert not is_conflict_entry("data/self/skills/note.md")