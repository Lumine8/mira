from fastapi import APIRouter, Depends

from app.models import FOUNDER_ROLE, User
from app.services.abuse import AbuseService
from app.services.identity import get_current_user

router = APIRouter(prefix="/abuse", tags=["abuse"])


@router.get("/status")
def abuse_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Current abuse score for the authenticated user."""
    service = AbuseService()
    return {
        "user_id": user.id,
        "abuse_score": service.get_score(user.id),
        "is_founder": user.role == FOUNDER_ROLE,
    }
