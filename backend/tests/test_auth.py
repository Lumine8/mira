import pytest

from app import deps


class _TokenSettings:
    mira_access_token = "sekrit"


class _NoTokenSettings:
    mira_access_token = ""


def _patch(monkeypatch, token: str) -> None:
    class S:
        mira_access_token = token

    monkeypatch.setattr(deps, "get_settings", lambda: S())


def test_verify_no_token_configured_allows_anything(monkeypatch) -> None:
    _patch(monkeypatch, "")
    deps._verify(None)
    deps._verify("")
    deps._verify("whatever")


def test_verify_requires_matching_token(monkeypatch) -> None:
    _patch(monkeypatch, "sekrit")
    deps._verify("sekrit")
    with pytest.raises(Exception):
        deps._verify("wrong")


def test_verify_rejects_missing_token(monkeypatch) -> None:
    _patch(monkeypatch, "sekrit")
    with pytest.raises(Exception):
        deps._verify(None)
    with pytest.raises(Exception):
        deps._verify("")


def test_ws_authorized_no_token_configured(monkeypatch) -> None:
    _patch(monkeypatch, "")
    assert deps.ws_authorized(None) is True
    assert deps.ws_authorized("") is True


def test_ws_authorized_requires_token(monkeypatch) -> None:
    _patch(monkeypatch, "sekrit")
    assert deps.ws_authorized("sekrit") is True
    assert deps.ws_authorized("wrong") is False
    assert deps.ws_authorized(None) is False