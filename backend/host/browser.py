"""Drive the user's Chrome (via CDP) to act on X for Mira.

Mira proposes [[x|...]] intents and the user approves them, exactly as before.
The difference is the hand that performs the action: instead of Twitter's paid
API (whose monthly credit pool can run dry), a real browser that is logged into
the account types the words and presses Post. The browser is the user's own
Chrome, launched with --remote-debugging-port=9222 so we can control it.

This module runs on the *host* (natively), where Chrome's debugging port at
127.0.0.1:9222 is reachable — not inside the API container.
"""

import json
import time
import urllib.parse

import requests
import websockets.sync.client as wsclient

CDP_HTTP = "http://127.0.0.1:9222"
COMPOSE_URL = "https://x.com/compose/post"
HOME_URL = "https://x.com/home"
LOAD_SECONDS = 30
POST_SECONDS = 45

# data-testid of the Post button inside the compose dialog, and of the toast
# that confirms a post went out. X has been stable on these selectors for years.
_SUBMIT_SEL = '[data-testid="tweetButton"]'
_TOAST_SEL = '[data-testid="toast"]'

# Chrome text stripped from profile pages before we keep the tweet bodies.
_UI_NOISE = {
    "Reposts", "Likes", "Posts", "Followers", "Following", "Follow",
    "Edit profile", "Home", "Explore", "Notifications", "Messages", "Bookmarks",
    "Lists", "Premium", "Verify", "Profile", "Settings and support", "Log out",
    "Search", "Grok", "Communities", "Verified Orgs", "Hashtags",
}


class BrowserXError(Exception):
    """User-readable failure while driving the browser."""


class _Tab:
    """A CDP websocket bound to one page target."""

    def __init__(self, ws_url: str) -> None:
        self._ws = wsclient.connect(ws_url, close_timeout=3)
        self._id = 0

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001 - already closed
            pass

    def cmd(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise BrowserXError(f"CDP {method} failed: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expression: str) -> object:
        return (
            self.cmd(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": True},
            )
            .get("result", {})
            .get("value")
        )


def open_tab(url: str) -> _Tab:
    """Open a fresh tab at `url` in the debug Chrome and wait for its JS to run."""
    try:
        resp = requests.put(
            f"{CDP_HTTP}/json/new?{urllib.parse.urlencode({'url': 'about:blank'})}", timeout=5
        )
        resp.raise_for_status()
        ws_url = resp.json().get("webSocketDebuggerUrl")
        if not ws_url:
            raise BrowserXError("Chrome gave no debug websocket for the new tab")
    except requests.RequestException as exc:
        raise BrowserXError(
            "Chrome's debug port (127.0.0.1:9222) isn't reachable — relaunch "
            "Chrome with --remote-debugging-port=9222 first."
        ) from exc
    tab = _Tab(ws_url)
    tab.cmd("Runtime.enable")
    tab.cmd("Page.enable")
    tab.cmd("Page.navigate", {"url": url})
    return tab


def _post_text_as(tab: _Tab, text: str) -> None:
    """Wait for the composer, then type the exact text. A contenteditable div
    (what X uses) changes via execCommand('insertText'), which fires real input
    events React picks up. A textarea falls back to a native value setter."""
    deadline = time.time() + LOAD_SECONDS
    found = False
    while time.time() < deadline:
        found = tab.eval(
            "(document.querySelector('[data-testid=\"tweetTextarea_0\"]') "
            "|| document.querySelector('div[contenteditable=\"true\"]')) !== null"
        )
        if found:
            break
        time.sleep(0.5)
    if not found:
        raise BrowserXError("the compose box never appeared on the page")
    js = r"""
    (() => {
      const ed = document.querySelector('[data-testid="tweetTextarea_0"]')
                || document.querySelector('[contenteditable="true"]');
      if (!ed) return false;
      ed.focus();
      if (ed.tagName === 'TEXTAREA' || ed.tagName === 'INPUT') {
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, 'value'
        );
        if (setter && setter.set) setter.set.call(ed, %s);
        else ed.value = %s;
        ed.dispatchEvent(new Event('input', { bubbles: true }));
      } else {
        document.execCommand('insertText', false, %s);
      }
      return true;
    })()
    """ % (json.dumps(text), json.dumps(text), json.dumps(text))
    if tab.eval(js) is not True:
        raise BrowserXError("could not find the compose box on the page")


def _submit(tab: _Tab) -> str:
    deadline = time.time() + POST_SECONDS
    while time.time() < deadline:
        clicked = tab.eval(
            f"(function(){{var b=document.querySelector({__import__('json').dumps(_SUBMIT_SEL)});"
            f"if(b){{b.click();return true;}}return false;}})()"
        )
        if clicked:
            break
        time.sleep(0.5)
    else:
        raise BrowserXError("could not find the Post button")
    # Wait for the app to show the 'Your post was sent' confirmation toast.
    deadline = time.time() + POST_SECONDS
    while time.time() < deadline:
        toast = tab.eval(
            f"(function(){{var t=document.querySelector({__import__('json').dumps(_TOAST_SEL)});"
            f"return t?t.textContent:null;}})()"
        )
        if toast:
            return str(toast).strip()
        time.sleep(0.5)
    return "posted (no toast yet — check the tab)"


def post_tweet(text: str) -> str:
    """Compose `text` in a fresh tab and press Post. Returns a confirmation."""
    text = text.strip()
    if not text:
        raise BrowserXError("nothing to post")
    if len(text) > 280:
        raise BrowserXError(f"that's too long for X ({len(text)} > 280)")
    tab = open_tab(COMPOSE_URL)
    try:
        tab.eval("document.visibilityState;")  # force the connection warm
        _post_text_as(tab, text)
        return _submit(tab)
    finally:
        tab.close()


def _logged_in_username(tab: _Tab) -> str:
    """Read the signed-in @handle from the sidebar, or '' if none is found."""
    return str(
        tab.eval(
            "(function(){"
            "var a=document.querySelector('a[aria-label*=\"/\"]');"  # too broad
            "return '';})()"
        )
        or ""
    )


def _logged_in_username(tab: _Tab) -> str:
    """Read the signed-in @handle from the account switcher in the bottom nav."""
    return str(
        tab.eval(
            "(function(){"
            "var b=document.querySelector('"
            '[data-testid="SideNav_AccountSwitcher_Button"]'
            "');"
            "if(!b)return '';"
            "var a=b.querySelector('a[href*=\"/\"]');"
            "if(!a)return '';"
            "var h=a.getAttribute('href')||'';"
            "return h.split('#')[0].replace(/^\\//,'');"
            "})()"
        )
        or ""
    )


def read_own_timeline(limit: int = 5) -> str:
    """Read the home timeline the signed-in account sees, as plain text.
    No API credits needed — it is the feed text the real browser renders."""
    tab = open_tab(HOME_URL)
    try:
        tab.eval("document.visibilityState;")
        time.sleep(4)
        body = tab.eval("document.body && document.body.innerText") or ""
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        kept = []
        for ln in lines:
            if ln in _UI_NOISE or len(ln) < 3 or not any(ch.isalnum() for ch in ln):
                continue
            if kept and kept[-1] == ln:
                continue
            kept.append(ln)
            if len(kept) >= limit * 3:
                break
        return "\n".join(kept)
    finally:
        tab.close()


def smoke() -> dict:
    """Open x.com home to prove CDP connectivity; returns page basics."""
    tab = open_tab(HOME_URL)
    try:
        url = tab.eval("location.href")
        title = tab.eval("document.title")
        return {"url": url, "title": title}
    finally:
        tab.close()


def is_logged_in() -> bool:
    """True when the profile is signed into X (the composer affordance exists)."""
    tab = open_tab(HOME_URL)
    try:
        tab.eval("document.visibilityState;")
        present = tab.eval(
            '(document.querySelector(\'[data-testid="SideNav_NewTweet_Button"]\') !== null)'
            " || (document.querySelector('[href=\"/compose/post\"]') !== null)"
        )
        return bool(present)
    finally:
        tab.close()


def check() -> dict:
    """Diagnostic: homepage load + signed-in state."""
    tab = open_tab(HOME_URL)
    try:
        tab.eval("document.visibilityState;")
        time.sleep(2)
        return {
            "url": tab.eval("location.href"),
            "signed_in": bool(
                tab.eval(
                    "(document.querySelector('[data-testid=\"SideNavbar_NewTweet_Button\"]') !== null) "
                    "|| (document.querySelector('[href=\"/compose/post\"]') !== null)"
                )
            ),
        }
    finally:
        tab.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        print(json.dumps(smoke()))