from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from app.models import Question, User
from app.services.questions.service import (
    QuestionService,
    next_after_simmer,
    normalize_question_text,
    questions_match,
    revisit,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Question.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _user_id(db) -> int:
    user = User(name="someone", role="person")
    db.add(user)
    db.commit()
    return user.id


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


# -- echo suppression -----------------------------------------------------------


def test_is_echo_true_for_open_question(db) -> None:
    svc = QuestionService(db, user_id=_user_id(db))
    svc.upsert("why do humans build solitary structures?")
    assert svc.is_echo("why do humans build solitary structures")
    assert svc.is_echo("Why do humans build solitary structures?")
    assert svc.is_echo("why do humans build solitary structures in dangerous places")


def test_is_echo_false_for_new_question(db) -> None:
    svc = QuestionService(db, user_id=_user_id(db))
    svc.upsert("why do humans build solitary structures?")
    assert not svc.is_echo("how do birds migrate")


def test_is_echo_ignores_empty_question(db) -> None:
    svc = QuestionService(db, user_id=_user_id(db))
    svc.upsert("why do humans build solitary structures?")
    assert not svc.is_echo("   ")


def test_is_echo_ignores_non_open_questions(db) -> None:
    svc = QuestionService(db, user_id=_user_id(db))
    question = svc.upsert("why do humans build solitary structures?")
    svc.mark_answered(question.id)
    assert not svc.is_echo("why do humans build solitary structures")
