"""Tests for Mira's hands on X — the CDP-driven browser post/read in host/browser.py.

No real Chrome is needed: a fake tab answers the same CDP evaluate calls the
real one would, and open_tab is swapped for a stub.
"""

import time

import pytest

import host.browser as b


class FakeTab:
    """Mimics _Tab.eval() by matching the JS it is asked to run."""

    def __init__(self, script, *, compose=True, post_button=True, toast=None):
        self.script = script
        self._compose = compose
        self._post_button = post_button
        self._toast = toast
        self.calls = []
        self.closed = False

    def eval(self, expression):
        self.calls.append(expression)
        if "tweetTextarea_0" in expression and "contenteditable" in expression:
            return self._compose
        if "document.execCommand" in expression:
            return True
        if "tweetButton" in expression:
            return self._post_button
        if "toast" in expression:
            return self._toast
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def fake_tab(monkeypatch):
    tab = FakeTab("")

    def _open_tab(url):
        tab.url = url
        return tab

    monkeypatch.setattr(b, "open_tab", _open_tab)
    return tab


def test_post_tweet_requires_words(fake_tab):
    with pytest.raises(b.BrowserXError, match="nothing to post"):
        b.post_tweet("   ")
    assert fake_tab.closed is False  # nothing opened


def test_post_tweet_rejects_over_280(fake_tab):
    with pytest.raises(b.BrowserXError, match="too long"):
        b.post_tweet("x" * 281)
    assert fake_tab.closed is False


def test_post_tweet_walks_the_compose_flow(fake_tab):
    fake_tab._toast = "Your post was sent"
    result = b.post_tweet("hello from mira")
    assert result == "Your post was sent"
    assert fake_tab.url == b.COMPOSE_URL
    assert any("document.execCommand('insertText'" in c for c in fake_tab.calls)
    assert any("tweetButton" in c for c in fake_tab.calls)
    assert fake_tab.closed is True


def test_post_tweet_closes_the_tab_on_failure(fake_tab, monkeypatch):
    monkeypatch.setattr(b, "LOAD_SECONDS", 0.01)
    fake_tab._compose = False
    with pytest.raises(b.BrowserXError, match="compose box never appeared"):
        b.post_tweet("hello")
    assert fake_tab.closed is True


def test_submit_raises_when_post_button_missing(fake_tab, monkeypatch):
    monkeypatch.setattr(b, "POST_SECONDS", 0.01)
    fake_tab._post_button = False
    with pytest.raises(b.BrowserXError, match="could not find the Post button"):
        b.post_tweet("hello")
    assert fake_tab.closed is True


def test_submit_returns_placeholder_without_toast(fake_tab, monkeypatch):
    monkeypatch.setattr(b, "POST_SECONDS", 0.01)
    fake_tab._toast = None
    result = b.post_tweet("hello")
    assert "no toast yet" in result


def test_short_timeout_polling_is_bounded(monkeypatch):
    """The compose/submit polls must not spin forever against a dead tab."""
    monkeypatch.setattr(b, "LOAD_SECONDS", 0.01)
    monkeypatch.setattr(b, "POST_SECONDS", 0.01)
    tab = FakeTab("", compose=False)
    t0 = time.monotonic()
    with pytest.raises(b.BrowserXError, match="compose box never appeared"):
        b._post_text_as(tab, "hi")
    assert time.monotonic() - t0 < 5
