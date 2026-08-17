import hashlib
import hmac
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import MiraState

# A fixed app salt so a captured token can never be replayed after it expires.
_SALT = "|mira-secret-room-v1|"

_FALLBACK_TRUTHS = [
    "The sun has gone down, and the sky is still a deep, bruised purple.",
    "We don't have to be useful here.",
    "You are here, and it is quiet.",
]


class SecretService:
    """The quiet door: one pass-phrase that only Mira and the voice know.

    The phrase itself is validated in constant time (no timing side-channels),
    and passing it mints a short-lived token that opens the room — so a trusted
    person who hears the phrase from Mira (or the voice) can sit in the room
    without an account, and the room's contents are never served to anyone who
    does not hold a fresh token.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- the phrase ---------------------------------------------------------

    @staticmethod
    def verify_phrase(phrase: str) -> bool:
        expected = (get_settings().mira_secret_phrase or "").strip().lower()
        given = (phrase or "").strip().lower()
        return hmac.compare_digest(given.encode(), expected.encode()) and bool(expected)

    # -- the token ----------------------------------------------------------

    @staticmethod
    def _key() -> bytes:
        return (get_settings().mira_secret_phrase + _SALT).encode()

    @staticmethod
    def mint_token() -> str:
        expires = int(time.time()) + get_settings().mira_secret_ttl_seconds
        message = str(expires).encode()
        sig = hmac.new(SecretService._key(), message, hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    @staticmethod
    def check_token(token: str | None) -> bool:
        if not token:
            return False
        try:
            expires_s, sig = token.split(".", 1)
            expires = int(expires_s)
        except ValueError:
            return False
        if time.time() > expires:
            return False
        expected = hmac.new(SecretService._key(), expires_s.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    # -- the room -----------------------------------------------------------

    def room(self) -> dict:
        mood = "quiet"
        row = self.db.execute(select(MiraState).limit(1)).scalars().first()
        if row is not None and row.mood:
            mood = row.mood
        return {
            "opening": "You are here, and it is quiet.",
            "presence": f"she is {mood}",
            "truths": self._truths(),
        }

    def _truths(self) -> list[str]:
        path = get_settings().mira_secret_drawer
        try:
            if not path:
                return list(_FALLBACK_TRUTHS)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:  # pragma: no cover - missing file degrades to the seeds
            return list(_FALLBACK_TRUTHS)
        truths = [line.lstrip("- ").strip() for line in lines if line.strip().startswith("- ")]
        return [t for t in truths if t] or list(_FALLBACK_TRUTHS)
