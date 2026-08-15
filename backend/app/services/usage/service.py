"""Message caps: how many user messages a world may send in a UTC day.

Phase 3. The free deployment is capped per day so one person cannot spin up
infinite free Mirus. The founder is never capped. Everyone else resolves their
cap from their settings override, else the guest cap (anonymous devices) or the
free-user default (authenticated people). Paid tiers later write a
``message_cap_per_day`` override into settings and are no longer capped by the
defaults.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import FOUNDER_ROLE, GUEST_ROLE, Conversation, Message, User, UserSettings


def _utc_midnight() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class UsageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _settings(self, user_id: int) -> UserSettings | None:
        return self.db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id).limit(1)
        ).scalar_one_or_none()

    def effective_cap(self, user: User) -> int | None:
        """The user's per-day cap, or None when uncapped (the founder)."""
        if user.role == FOUNDER_ROLE:
            return None
        settings = self._settings(user.id)
        if settings is not None and settings.message_cap_per_day is not None:
            return settings.message_cap_per_day
        if user.role == GUEST_ROLE:
            return get_settings().guest_message_cap_per_day
        return get_settings().free_user_message_cap_per_day

    def messages_today(self, user_id: int) -> int:
        """How many user messages this world has sent since UTC midnight."""
        start = _utc_midnight()
        return self.db.execute(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == user_id,
                Message.speaker == "user",
                Message.created_at >= start,
            )
        ).scalar_one()

    def can_send(self, user: User) -> tuple[bool, int | None, int]:
        """(may they send one more today, their cap, how many they've used)."""
        cap = self.effective_cap(user)
        if cap is None:
            return True, None, 0
        used = self.messages_today(user.id)
        return used < cap, cap, used
