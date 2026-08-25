from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TIER_FREE = "free"
TIER_FOUNDING = "founding"
TIER_CONTINUITY = "continuity"
ALL_TIERS = [TIER_FREE, TIER_FOUNDING, TIER_CONTINUITY]

# Feature caps per tier
TIER_CAPS = {
    TIER_FREE: {"messages_per_day": 20, "memory_days": 7, "voice": False, "documents": False, "skills": False, "research": False},
    TIER_FOUNDING: {"messages_per_day": -1, "memory_days": -1, "voice": True, "documents": True, "skills": True, "research": True},
    TIER_CONTINUITY: {"messages_per_day": -1, "memory_days": -1, "voice": True, "documents": True, "skills": True, "research": True},
}

TIER_PRICES = {
    TIER_FREE: {"amount": 0, "currency": "usd", "interval": None},
    TIER_FOUNDING: {"amount": 100, "currency": "usd", "interval": None},  # $1 one-time (in cents)
    TIER_CONTINUITY: {"amount": 500, "currency": "usd", "interval": "month"},  # $5/month (in cents)
}


class Subscription(Base):
    """A user's subscription state. One active subscription per user."""
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    tier: Mapped[str] = mapped_column(String(16), default=TIER_FREE, server_default=TIER_FREE)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageRecord(Base):
    """Per-user daily usage tracking for margin calculation."""
    __tablename__ = "usage_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    messages_sent: Mapped[int] = mapped_column(Integer, default=0)
    inference_tokens: Mapped[int] = mapped_column(Integer, default=0)
    inference_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    storage_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
