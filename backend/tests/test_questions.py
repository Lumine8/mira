from app.services.questions.service import (
    next_after_simmer,
    normalize_question_text,
    questions_match,
    revisit,
)


def test_normalize_whitespace_case_and_trailing_punct() -> None:
    assert normalize_question_text("  Why do humans build solitary structures?  ") == "why do humans build solitary structures"
    assert normalize_question_text("Why\nbuild   structures") == "why build structures"


def test_questions_match_exact() -> None:
    assert questions_match("why do humans build solitary structures in dangerous places", "why do humans build solitary structures in dangerous places")
    assert questions_match("  Why do humans build solitary structures?  ", "why do humans build solitary structures")


def test_questions_match_contains() -> None:
    assert questions_match("do humans build solitary structures", "why do humans build solitary structures in dangerous places")
    assert not questions_match("why do humans build structures", "how do birds migrate")


def test_questions_match_short_phrases_not_merged() -> None:
    # Too short to be safely merged by containment ("rain" vs "drain").
    assert not questions_match("rain", "drain")


def test_simmer_fades_slowly() -> None:
    assert next_after_simmer(50, hours=12.0) == 44
    assert next_after_simmer(10, hours=24.0) == 0


def test_simmer_capped_hours_and_never_negative() -> None:
    assert next_after_simmer(100, hours=9999) == 76  # capped at 48h → −24
    assert next_after_simmer(2, hours=10) == 0


def test_revisit_boosts_and_caps() -> None:
    assert revisit(50) == 55
    assert revisit(97) == 100
    assert revisit(100) == 100
