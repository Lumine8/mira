"""Tests for the readable-page endpoint — the words Mira reads in her window."""

import asyncio
import pytest

import app.api.routes.browser as browser


def test_extract_title() -> None:
    assert browser._extract_title("<title>  The   Page </title>") == "The Page"
    assert browser._extract_title("<html><body>x</body></html>") == ""
    assert browser._extract_title("<TITLE>Case</TITLE>") == "Case"


def test_readable_strips_markup_and_truncates() -> None:
    content = browser._page_to_text(
        "<html><head><title>T</title></head><body>"
        "<script>var x = 1;</script><p>Hello   world</p>"
        "</body></html>"
    )
    assert "Hello world" in content
    assert "script" not in content.lower()


def test_page_to_text_prefers_main_region() -> None:
    """Navigation chrome is dropped when the page has a main/article region."""
    content = browser._page_to_text(
        "<html><body><nav>Log In  Markets  Videos</nav>"
        "<article><h1>The Writing</h1><p>Real   article body here.</p></article>"
        "<footer>About us</footer></body></html>"
    )
    assert "Real article body here." in content
    assert "Log In" not in content


@pytest.mark.asyncio
async def test_readable_reports_fetch_failure(monkeypatch) -> None:
    class _Broken:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, *exc) -> bool:
            return False

    monkeypatch.setattr(browser.httpx, "AsyncClient", _Broken)
    monkeypatch.setattr(browser, "_backup_text", lambda url: None)
    result = await browser.browse_readable("https://example.invalid/x", _=None)
    assert result["url"] == "https://example.invalid/x"
    assert result["content"].startswith("[error]")


@pytest.mark.asyncio
async def test_readable_uses_backup_reader_when_direct_fetch_refused(monkeypatch) -> None:
    """A site that refuses the direct fetch still yields its words through the
    backup reader, so the window shows content instead of an error."""
    class _Broken:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, *exc) -> bool:
            return False

    monkeypatch.setattr(browser.httpx, "AsyncClient", _Broken)
    monkeypatch.setattr(browser, "_backup_text", lambda url: "backup words for the page")
    result = await browser.browse_readable("https://www.investopedia.com/terms/b/bullmarket.asp", _=None)
    assert result["content"] == "backup words for the page"


def test_reader_text_extracts_words(monkeypatch) -> None:
    """The backup reader returns what the proxy rendered, capped like a page."""
    from app.services.tools.service import _reader_text

    class FakeResp:
        text = "Here is the page, rendered as words."
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("app.services.tools.service.httpx.get", lambda *a, **k: FakeResp())
    assert _reader_text("https://www.investopedia.com/x") == "Here is the page, rendered as words."


def test_reader_text_strips_header_and_nav(monkeypatch) -> None:
    """The proxy's metadata header and the site's navigation are cut so the
    writing is what Mira actually reads."""
    from app.services.tools.service import _reader_text

    class FakeResp:
        text = (
            "Title: Bull Markets Explained: Features and Historical Instances\n\n"
            "URL Source: https://www.investopedia.com/terms/b/bullmarket.asp\n\n"
            "Published Time: 2026-08-01\n\n"
            "Markdown Content:\n"
            "*   [Log In](https://www.investopedia.com/auth)\n"
            "*   [Markets](https://www.investopedia.com/markets)\n"
            "\n"
            "A bull market is a period of rising prices.\n"
            "Traders look for signs of the trend.\n"
        )
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("app.services.tools.service.httpx.get", lambda *a, **k: FakeResp())
    out = _reader_text("https://www.investopedia.com/x")
    assert out is not None
    assert "Bull Markets Explained" not in out
    assert "Markdown Content" not in out
    assert "Log In" not in out
    assert "A bull market is a period of rising prices." in out
    assert "Traders look for signs of the trend." in out


def test_reader_text_rejects_reader_error_warnings(monkeypatch) -> None:
    """A proxy warning (404, captcha) is a refusal, not content."""
    from app.services.tools.service import _reader_text

    class FakeResp:
        text = "Warning: Target URL returned error 404: Not Found"
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("app.services.tools.service.httpx.get", lambda *a, **k: FakeResp())
    assert _reader_text("https://www.investopedia.com/x") is None