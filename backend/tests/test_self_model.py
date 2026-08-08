from app.services.self.service import (
    _OTHER_DELIVERY_CHARS,
    _clean,
    _clamp,
    _delivery_text,
    _num,
    extract_json,
)


def test_extract_json_plain_object() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_inside_fences() -> None:
    text = 'Sure, here you go:\n```json\n{"mood": "curious"}\n```\n'
    assert extract_json(text) == {"mood": "curious"}


def test_extract_json_ignores_prefix_and_suffix() -> None:
    text = 'thinking... {"summary": "hi", "topics": ["a", "b"]} and more'
    parsed = extract_json(text)
    assert parsed == {"summary": "hi", "topics": ["a", "b"]}


def test_extract_json_garbage_returns_none() -> None:
    assert extract_json("no json here at all") is None
    assert extract_json("") is None
    assert extract_json("{unbalanced") is None


def test_extract_json_tolerates_trailing_comma() -> None:
    assert extract_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_extract_json_non_dict_returns_none() -> None:
    assert extract_json("[1, 2, 3]") is None


def test_helpers() -> None:
    assert _clean("  hi  ") == "hi"
    assert _clean(123) == ""
    assert _num("0.15", 0.0) == 0.15
    assert _num("nope", 0.0) == 0.0
    assert _clamp(1.4) == 1.0
    assert _clamp(-0.2) == 0.0
    assert _clamp(0.5) == 0.5


def test_delivery_chars_browse_grows_with_scale() -> None:
    from types import SimpleNamespace

    browse = SimpleNamespace(kind="browse_url", result="x" * 5000, payload={})
    other = SimpleNamespace(kind="play_song", result="y" * 5000, payload={})
    assert len(_delivery_text(browse)) == 3000
    assert len(_delivery_text(other)) == 900
    assert _OTHER_DELIVERY_CHARS == 900
