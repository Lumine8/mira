"""Billing service: tier management, Stripe integration, usage tracking."""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, func as sql_func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.billing import (
    TIER_FREE, TIER_FOUNDING, TIER_CONTINUITY, ALL_TIERS, TIER_CAPS,
    Subscription, UsageRecord,
)
from app.models.user import User

logger = logging.getLogger("mira.billing")

_STRIPE_API = "https://api.stripe.com/v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BillingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_subscription(self, user_id: int) -> Subscription | None:
        return self.db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        ).scalar_one_or_none()

    def get_or_create_subscription(self, user_id: int) -> Subscription:
        sub = self.get_subscription(user_id)
        if sub is None:
            sub = Subscription(user_id=user_id, tier=TIER_FREE)
            self.db.add(sub)
            self.db.commit()
            self.db.refresh(sub)
        return sub

    def get_tier(self, user_id: int) -> str:
        """Resolve a user's effective tier. Founder always gets founding."""
        user = self.db.get(User, user_id)
        if user and user.role == "founder":
            return TIER_FOUNDING
        sub = self.get_subscription(user_id)
        if sub is None:
            return TIER_FREE
        return sub.tier

    def get_caps(self, user_id: int) -> dict:
        tier = self.get_tier(user_id)
        return TIER_CAPS.get(tier, TIER_CAPS[TIER_FREE])

    def can_send(self, user_id: int) -> tuple[bool, int, int]:
        """Check if user can send a message. Returns (allowed, cap, used)."""
        caps = self.get_caps(user_id)
        cap = caps["messages_per_day"]
        if cap == -1:  # unlimited
            return True, -1, 0
        used = self._messages_today(user_id)
        return used < cap, cap, used

    def _messages_today(self, user_id: int) -> int:
        today = _now().strftime("%Y-%m-%d")
        record = self.db.execute(
            select(UsageRecord).where(
                UsageRecord.user_id == user_id,
                UsageRecord.date == today,
            )
        ).scalar_one_or_none()
        return record.messages_sent if record else 0

    def record_message(self, user_id: int, *, tokens: int = 0, cost_cents: int = 0) -> None:
        today = _now().strftime("%Y-%m-%d")
        record = self.db.execute(
            select(UsageRecord).where(
                UsageRecord.user_id == user_id,
                UsageRecord.date == today,
            )
        ).scalar_one_or_none()
        if record is None:
            record = UsageRecord(user_id=user_id, date=today)
            self.db.add(record)
        record.messages_sent += 1
        record.inference_tokens += tokens
        record.inference_cost_cents += cost_cents
        self.db.commit()

    # --- Stripe integration ---

    def create_checkout_session(self, user_id: int, tier: str) -> dict | None:
        """Create a Stripe Checkout session for upgrading to a paid tier."""
        settings = get_settings()
        if not settings.stripe_secret_key:
            logger.warning("Stripe not configured, cannot create checkout session")
            return None

        price_map = {
            TIER_FOUNDING: settings.stripe_founding_price_id,
            TIER_CONTINUITY: settings.stripe_continuity_price_id,
        }
        price_id = price_map.get(tier)
        if not price_id:
            return None

        user = self.db.get(User, user_id)
        if user is None:
            return None

        # Get or create Stripe customer
        sub = self.get_or_create_subscription(user_id)
        customer_id = sub.stripe_customer_id
        if not customer_id:
            customer_id = self._create_stripe_customer(user)
            sub.stripe_customer_id = customer_id
            self.db.commit()

        try:
            resp = httpx.post(
                f"{_STRIPE_API}/checkout/sessions",
                auth=("sk_live_" + settings.stripe_secret_key if not settings.stripe_secret_key.startswith("sk_") else settings.stripe_secret_key, ""),
                data={
                    "customer": customer_id,
                    "mode": "subscription" if tier == TIER_CONTINUITY else "payment",
                    "line_items[0][price]": price_id,
                    "line_items[0][quantity]": 1,
                    "success_url": f"{settings.frontend_url}/auth?upgraded={tier}",
                    "cancel_url": f"{settings.frontend_url}/auth?cancelled=1",
                    "metadata[user_id]": str(user_id),
                    "metadata[tier]": tier,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("stripe checkout failed: %s", exc)
            return None

    def _create_stripe_customer(self, user: User) -> str:
        settings = get_settings()
        resp = httpx.post(
            f"{_STRIPE_API}/customers",
            auth=(settings.stripe_secret_key, ""),
            data={
                "email": user.email or "",
                "name": user.name,
                "metadata[user_id]": str(user.id),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def handle_stripe_webhook(self, payload: dict, sig_header: str | None = None) -> bool:
        """Process a Stripe webhook event."""
        event_type = payload.get("type", "")
        data = payload.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            return self._handle_checkout_completed(data)
        elif event_type == "invoice.paid":
            return self._handle_invoice_paid(data)
        elif event_type == "customer.subscription.deleted":
            return self._handle_subscription_deleted(data)
        elif event_type == "customer.subscription.updated":
            return self._handle_subscription_updated(data)

        logger.info("unhandled stripe event: %s", event_type)
        return True

    def _handle_checkout_completed(self, data: dict) -> bool:
        user_id = int(data.get("metadata", {}).get("user_id", 0))
        tier = data.get("metadata", {}).get("tier", TIER_FREE)
        sub_id = data.get("subscription")
        customer = data.get("customer")

        if not user_id:
            return False

        sub = self.get_or_create_subscription(user_id)
        sub.tier = tier
        if customer:
            sub.stripe_customer_id = customer
        if sub_id:
            sub.stripe_subscription_id = sub_id
            sub.status = "active"
        self.db.commit()
        logger.info("user %d upgraded to %s", user_id, tier)
        return True

    def _handle_invoice_paid(self, data: dict) -> bool:
        customer = data.get("customer")
        if not customer:
            return False
        sub = self.db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer)
        ).scalar_one_or_none()
        if sub is None:
            return False
        sub.status = "active"
        period_start = data.get("period_start")
        period_end = data.get("period_end")
        if period_start:
            sub.current_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)
        if period_end:
            sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
        self.db.commit()
        return True

    def _handle_subscription_deleted(self, data: dict) -> bool:
        sub_id = data.get("id")
        if not sub_id:
            return False
        sub = self.db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        ).scalar_one_or_none()
        if sub is None:
            return False
        sub.tier = TIER_FREE
        sub.stripe_subscription_id = None
        sub.stripe_price_id = None
        sub.status = "canceled"
        self.db.commit()
        logger.info("user %d downgraded to free", sub.user_id)
        return True

    def _handle_subscription_updated(self, data: dict) -> bool:
        sub_id = data.get("id")
        status = data.get("status")
        if not sub_id:
            return False
        sub = self.db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        ).scalar_one_or_none()
        if sub is None:
            return False
        if status:
            sub.status = status
        self.db.commit()
        return True

    # --- Margin tracking ---

    def usage_summary(self, days: int = 30) -> dict:
        """Aggregate usage across all users for margin calculation."""
        cutoff = _now().strftime("%Y-%m-%d")
        # Simple: count all records
        records = self.db.execute(select(UsageRecord)).scalars().all()
        total_messages = sum(r.messages_sent for r in records)
        total_tokens = sum(r.inference_tokens for r in records)
        total_cost = sum(r.inference_cost_cents for r in records)
        unique_users = len({r.user_id for r in records})
        return {
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "total_cost_cents": total_cost,
            "unique_users": unique_users,
            "avg_cost_per_user_cents": total_cost // max(unique_users, 1),
        }
