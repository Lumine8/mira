"""Billing service: tier management, Razorpay integration, usage tracking."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.billing import (
    TIER_CAPS,
    TIER_CONTINUITY,
    TIER_FOUNDING,
    TIER_FREE,
    Subscription,
    UsageRecord,
)
from app.models.user import User

logger = logging.getLogger("mira.billing")

_RAZORPAY_API = "https://api.razorpay.com/v1"


def _now() -> datetime:
    return datetime.now(UTC)


class BillingService:
    _processed_events: set[str] = set()

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
        if cap == -1:
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

    # --- Razorpay integration (https://razorpay.me/) ---

    def _razorpay_auth(self) -> tuple[str, str]:
        settings = get_settings()
        return (settings.razorpay_key_id, settings.razorpay_key_secret)

    def create_checkout_session(self, user_id: int, tier: str) -> dict | None:
        """Create a Razorpay subscription or one-time payment link."""
        settings = get_settings()
        if not settings.razorpay_key_id:
            logger.warning("Razorpay not configured, cannot create checkout session")
            return None

        plan_map = {
            TIER_FOUNDING: settings.razorpay_founding_plan_id,
            TIER_CONTINUITY: settings.razorpay_continuity_plan_id,
        }
        plan_id = plan_map.get(tier)
        if not plan_id:
            return None

        user = self.db.get(User, user_id)
        if user is None:
            return None

        sub = self.get_or_create_subscription(user_id)
        customer_id = sub.stripe_customer_id  # reuse field for razorpay_customer_id
        if not customer_id:
            customer_id = self._create_razorpay_customer(user)
            sub.stripe_customer_id = customer_id
            self.db.commit()

        try:
            resp = httpx.post(
                f"{_RAZORPAY_API}/subscriptions",
                auth=self._razorpay_auth(),
                json={
                    "plan_id": plan_id,
                    "customer_id": customer_id,
                    "total_count": 0 if tier == TIER_CONTINUITY else 1,
                    "notes": {"user_id": str(user_id), "tier": tier},
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"id": data.get("id"), "short_url": data.get("short_url")}
        except Exception as exc:
            logger.warning("razorpay subscription failed: %s", exc)
            return None

    def _create_razorpay_customer(self, user: User) -> str:
        get_settings()
        resp = httpx.post(
            f"{_RAZORPAY_API}/customers",
            auth=self._razorpay_auth(),
            json={
                "email": user.email or "",
                "name": user.name,
                "notes": {"user_id": str(user.id)},
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def handle_razorpay_webhook(self, raw_body: bytes, sig_header: str | None = None) -> bool:
        """Process a Razorpay webhook event with HMAC-SHA256 signature verification."""
        settings = get_settings()

        if settings.razorpay_webhook_secret and sig_header:
            if not self._verify_razorpay_signature(raw_body, sig_header, settings.razorpay_webhook_secret):
                logger.warning("razorpay webhook signature verification failed")
                return False

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            logger.warning("razorpay webhook: invalid JSON body")
            return False

        event_id = payload.get("id")
        if event_id:
            if event_id in self._processed_events:
                logger.info("razorpay webhook: duplicate event %s, skipping", event_id)
                return True
            self._processed_events.add(event_id)
            if len(self._processed_events) > 10_000:
                self._processed_events = set(list(self._processed_events)[-5_000:])

        event = payload.get("event", "")
        payload_data = payload.get("payload", {})

        if event == "subscription.activated":
            return self._handle_subscription_activated(payload_data)
        elif event == "subscription.charged":
            return self._handle_subscription_charged(payload_data)
        elif event == "subscription.cancelled":
            return self._handle_subscription_cancelled(payload_data)
        elif event == "subscription.paused":
            return self._handle_subscription_paused(payload_data)

        logger.info("unhandled razorpay event: %s", event)
        return True

    def _verify_razorpay_signature(self, raw_body: bytes, sig_header: str, secret: str) -> bool:
        """Verify Razorpay webhook HMAC-SHA256 signature against the raw bytes.

        Razorpay sends ``X-Razorpay-Signature`` as a hex digest of
        HMAC-SHA256(secret, raw_body).
        """
        try:
            expected = hmac.new(
                secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, sig_header)
        except Exception as exc:
            logger.warning("razorpay signature check error: %s", exc)
            return False

    def _handle_subscription_activated(self, data: dict) -> bool:
        sub_data = data.get("subscription", {}).get("entity", {})
        notes = sub_data.get("notes", {})
        user_id = int(notes.get("user_id", 0))
        tier = notes.get("tier", TIER_FREE)
        if not user_id:
            return False
        sub = self.get_or_create_subscription(user_id)
        sub.tier = tier
        sub.status = "active"
        sub.stripe_subscription_id = sub_data.get("id", "")
        self.db.commit()
        logger.info("user %d subscription activated (%s)", user_id, tier)
        return True

    def _handle_subscription_charged(self, data: dict) -> bool:
        payment = data.get("payment", {}).get("entity", {})
        subscription_id = payment.get("subscription_id", "")
        if not subscription_id:
            return False
        sub = self.db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        ).scalar_one_or_none()
        if sub:
            sub.status = "active"
            self.db.commit()
            logger.info("subscription %s charged successfully", subscription_id)
        return True

    def _handle_subscription_cancelled(self, data: dict) -> bool:
        sub_data = data.get("subscription", {}).get("entity", {})
        subscription_id = sub_data.get("id", "")
        if not subscription_id:
            return False
        sub = self.db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        ).scalar_one_or_none()
        if sub:
            sub.status = "cancelled"
            sub.tier = TIER_FREE
            self.db.commit()
            logger.info("subscription %s cancelled", subscription_id)
        return True

    def _handle_subscription_paused(self, data: dict) -> bool:
        sub_data = data.get("subscription", {}).get("entity", {})
        subscription_id = sub_data.get("id", "")
        if not subscription_id:
            return False
        sub = self.db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        ).scalar_one_or_none()
        if sub:
            sub.status = "paused"
            self.db.commit()
            logger.info("subscription %s paused", subscription_id)
        return True

    def usage_summary(self, days: int = 30) -> dict:
        """Aggregate usage across all users for margin calculation."""
        from datetime import timedelta

        cutoff = _now() - timedelta(days=days)
        records = self.db.execute(
            select(UsageRecord).where(UsageRecord.created_at >= cutoff)
        ).scalars().all()
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
