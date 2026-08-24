"""Public endpoints for data disclosures and age verification."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import FOUNDER_ROLE, User
from app.services.identity import get_current_user

router = APIRouter(prefix="/disclaimers", tags=["disclaimers"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgeConfirmation(BaseModel):
    age_verified: bool
    age: int


class DisclaimerOut(BaseModel):
    age_gate_required: bool
    minimum_age: int
    privacy_url: str
    terms_url: str


@router.get("/", response_model=DisclaimerOut)
def get_disclaimers() -> DisclaimerOut:
    s = get_settings()
    return DisclaimerOut(
        age_gate_required=s.age_gate_enabled,
        minimum_age=s.minimum_age,
        privacy_url=s.privacy_url,
        terms_url=s.terms_url,
    )


@router.post("/age-verify")
def verify_age(
    payload: AgeConfirmation,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Record the user's age confirmation. The founder is exempt from the
    age gate."""
    if user.role == FOUNDER_ROLE:
        return {"ok": True, "exempt": True}
    if not payload.age_verified or payload.age < get_settings().minimum_age:
        raise HTTPException(
            status_code=403,
            detail=f"you must be at least {get_settings().minimum_age} to use Mira",
        )
    user.age_verified = True
    user.age_verified_at = _now()
    user.age_verified_source = "self_declaration"
    db.commit()
    return {"ok": True, "age": payload.age}
