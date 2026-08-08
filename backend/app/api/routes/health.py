import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()

    db_status = "ok"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"

    ollama_status = "ok"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            if resp.status_code != 200:
                ollama_status = "unavailable"
    except Exception:
        ollama_status = "unavailable"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        ollama=ollama_status,
        provider=settings.ai_provider,
        ollama_model=settings.ollama_llm_model if ollama_status == "ok" else None,
    )
