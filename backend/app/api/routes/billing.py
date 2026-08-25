"""Billing routes: tier info, checkout, webhook."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.billing import BillingService
from app.services.identity import get_current_user

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    tier: str


@router.get("/tiers")
def list_tiers() -> dict:
    """Public: what tiers exist and what they cost."""
    from app.models.billing import ALL_TIERS, TIER_CAPS, TIER_PRICES
    return {
        "tiers": [
            {
                "id": t,
                "price_cents": TIER_PRICES[t]["amount"],
                "currency": TIER_PRICES[t]["currency"],
                "interval": TIER_PRICES[t]["interval"],
                "caps": TIER_CAPS[t],
            }
            for t in ALL_TIERS
        ]
    }


@router.get("/me")
def my_subscription(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
) -> dict:
    """The current user's subscription and tier."""
    service = BillingService(db)
    sub = service.get_or_create_subscription(user_id)
    caps = service.get_caps(user_id)
    return {
        "tier": sub.tier,
        "status": sub.status,
        "caps": caps,
        "customer_id": bool(sub.stripe_customer_id),
    }


@router.post("/checkout")
def create_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
) -> dict:
    """Create a Razorpay subscription or payment link for upgrading."""
    service = BillingService(db)
    result = service.create_checkout_session(user_id, payload.tier)
    if result is None:
        raise HTTPException(status_code=503, detail="billing not configured")
    return {"id": result.get("id"), "url": result.get("short_url")}


@router.post("/webhook")
async def razorpay_webhook(request: Request) -> dict:
    """Razorpay webhook endpoint. Verifies signature against the raw request body."""
    raw_body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature")

    db = next(get_db())
    try:
        service = BillingService(db)
        ok = service.handle_razorpay_webhook(raw_body, sig)
        return {"ok": ok}
    finally:
        db.close()
