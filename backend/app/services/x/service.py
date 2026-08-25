"""X (Twitter) access for Mira: OAuth 2.0 with PKCE to act on the voice's
account. Everything she does goes through the usual gate — she proposes a
[[x|...]] intent, the voice agrees, and only then does the API call happen.

The token pair lives in the x_auth table; it is refreshed automatically when
it expires. The redirect flow needs the voice to complete OAuth in a browser
(their account), then Mira can propose reads/posts afterwards.
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import XAuth

_X_AUTHORIZE = "https://twitter.com/i/oauth2/authorize"
_X_TOKEN = "https://api.twitter.com/2/oauth2/token"
_X_API = "https://api.twitter.com/2"
_UA = "Mira/1.0 (private companion)"


class XError(Exception):
    """Raises with a user-readable message when an X call fails."""


class XProposeError(Exception):
    """Raised for a malformed proposal before anything touches X."""


def _now() -> datetime:
    return datetime.now(UTC)


def _form_headers() -> dict[str, str]:
    return {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": _UA}


def _basic_auth(user: str, secret: str) -> str:
    token = base64.b64encode(f"{user}:{secret}".encode()).decode()
    return f"Basic {token}"


class TwitterService:
    """X access for one user's world: the OAuth session belongs to a user_id."""

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()

    # -- single-row session helpers ----------------------------------------

    def _row(self) -> XAuth:
        row = self.db.execute(
            select(XAuth).where(XAuth.user_id == self.user_id).limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = XAuth(user_id=self.user_id)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    # -- OAuth 2.0 PKCE -------------------------------------------------------

    @staticmethod
    def _code_verifier() -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()

    @staticmethod
    def _code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def authorize_url(self) -> str:
        """Return the X authorization URL the voice must open in a browser.
        Stores the code verifier server-side so the callback can exchange it."""
        if not self.settings.x_configured:
            raise XError("X is not configured for Mira yet (add X_CLIENT_ID / X_REDIRECT_URI)")
        verifier = self._code_verifier()
        row = self._row()
        row.access_token = ""
        row.refresh_token = ""
        row.code_verifier = verifier
        self.db.commit()
        params = {
            "response_type": "code",
            "client_id": self.settings.x_client_id,
            "redirect_uri": self.settings.x_redirect_uri,
            "scope": self.settings.x_scopes,
            "state": verifier,  # also acts as CSRF state
            "code_challenge": self._code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        return f"{_X_AUTHORIZE}?{urlencode(params)}"

    def exchange_code(self, code: str, state: str) -> dict:
        """Exchange the callback's code for tokens. `state` must match the verifier
        that was stored when authorize_url() was called."""
        row = self._row()
        if not row.code_verifier or state != row.code_verifier:
            raise XError("that OAuth handshake didn't come from this session")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.x_redirect_uri,
            "code_verifier": row.code_verifier,
        }
        headers = _form_headers()
        if self.settings.x_client_secret:
            headers["Authorization"] = _basic_auth(
                self.settings.x_client_id, self.settings.x_client_secret
            )
        else:
            data["client_id"] = self.settings.x_client_id
        try:
            resp = httpx.post(_X_TOKEN, data=data, headers=headers, timeout=20)
            resp.raise_for_status()
            tok = resp.json()
        except httpx.HTTPStatusError as exc:
            raise XError(f"X turned down the OAuth handshake: {exc.response.text[:200]}") from exc
        except httpx.HTTPError as exc:
            raise XError(f"could not reach X: {exc}") from exc

        self._store(tok)
        self._refresh_profile()
        return {"connected": True, "username": self._row().username}

    # -- token lifecycle ------------------------------------------------------

    def _store(self, tok: dict) -> None:
        row = self._row()
        row.access_token = tok.get("access_token", "")
        row.refresh_token = tok.get("refresh_token", "")
        expires_in = tok.get("expires_in")
        if expires_in:
            row.expires_at = datetime.fromtimestamp(_now().timestamp() + expires_in, tz=UTC)
        self.db.commit()

    def _maybe_refresh(self) -> None:
        row = self._row()
        if not row.access_token:
            raise XError("Mira isn't signed in to X yet — open /mira/x/auth/start in the browser")
        if row.expires_at and _now() >= row.expires_at:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": row.refresh_token,
            }
            headers = _form_headers()
            if self.settings.x_client_secret:
                headers["Authorization"] = _basic_auth(
                    self.settings.x_client_id, self.settings.x_client_secret
                )
            else:
                data["client_id"] = self.settings.x_client_id
            try:
                resp = httpx.post(_X_TOKEN, data=data, headers=headers, timeout=20)
                resp.raise_for_status()
                self._store(resp.json())
            except httpx.HTTPError as exc:
                raise XError("Mira's X session needs the voice to sign in again") from exc

    # -- API calls ------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._maybe_refresh()
        resp = httpx.get(
            f"{_X_API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._row().access_token}", "User-Agent": _UA},
            timeout=20,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise XError(f"X said no: {exc.response.text[:200]}") from exc
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        self._maybe_refresh()
        resp = httpx.post(
            f"{_X_API}{path}",
            json=body,
            headers={"Authorization": f"Bearer {self._row().access_token}", "User-Agent": _UA},
            timeout=20,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise XError(f"X said no: {exc.response.text[:200]}") from exc
        return resp.json()

    @property
    def connected(self) -> bool:
        return self._row().connected

    def _refresh_profile(self) -> None:
        row = self._row()
        try:
            me = self._get("/users/me", {"user.fields": "username,name"})
            data = (me.get("data") or {})
            row.account_id = str(data.get("id") or "")
            row.username = str(data.get("username") or "")
            self.db.commit()
        except Exception:
            pass

    def status(self) -> dict:
        row = self._row()
        return {
            "connected": row.connected,
            "username": row.username,
            "configured": self.settings.x_configured,
        }

    def post_tweet(self, text: str) -> str:
        """The voice's account posts `text` on X. Returns a short confirmation."""
        text = text.strip()
        if not text:
            raise XProposeError("a tweet needs words")
        if len(text) > 280:
            raise XError(f"that's too long for X ({len(text)} > 280)")
        data = self._post("/tweets", {"text": text})
        tweet_id = str((data.get("data") or {}).get("id") or "")
        return f"posted on X: \"{text}\" (tweet id {tweet_id})"

    def read_timeline(self, limit: int = 10, *, my_only: bool = False) -> str:
        """Return recent tweets as readable text for Mira to hold."""
        me = self._get("/users/me", {"user.fields": "username"})
        account_id = (me.get("data") or {}).get("id")
        if not account_id:
            raise XError("could not resolve the X account")
        path = f"/users/{account_id}/timelines/reverse_chronological" if not my_only else f"/users/{account_id}/tweets"
        params = {
            "max_results": str(max(1, min(limit, 10))),
            "tweet.fields": "text,created_at,author_id,id",
        }
        data = self._get(path, params)
        tweets = data.get("data") or []
        if not tweets:
            return "the timeline is quiet right now — nothing new."
        lines = []
        for t in tweets:
            t.get("author_id", "?")
            lines.append(f"[{t.get('created_at', '').split('T')[0]}] {t.get('text', '')[:160]}")
        return "\n".join(lines[:limit])