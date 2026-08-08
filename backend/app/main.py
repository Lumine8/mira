from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.session import engine
from app.deps import get_provider
from app.services.mind.service import MindLoop

setup_logging()
logger = get_logger(__name__)

mind = MindLoop(get_provider())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("database connection ok")
    except Exception as exc:  # pragma: no cover - startup path
        logger.warning("database unavailable at startup: %s", exc)

    logger.info(
        "%s starting (env=%s, provider=%s, model=%s)",
        settings.app_name,
        settings.environment,
        settings.ai_provider,
        settings.gemini_text_model if settings.ai_provider == "gemini" else settings.ollama_llm_model,
    )
    if settings.perception_enabled:
        mind.start()
        logger.info("mind loop started (heartbeat=%ss)", settings.mind_heartbeat_seconds)
    yield
    mind.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
