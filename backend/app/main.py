import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.base import Base
from app.db.session import engine
from app.deps import get_provider
from app.services.ai.prompt_builder import warm_weather
from app.services.mind.service import MindLoop
from app.services.mote.service import MoteLoop
from app.services.reminders.service import ReminderLoop

setup_logging()
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Dual-mode loop lifecycle
# ---------------------------------------------------------------------------
# Single-process (default): the process-global loops below run in the same
# event-loop as the API.  Works perfectly for SQLite / local dev.
#
# Worker mode (MIRA_WORKER_MODE=true): the same loops still start, but each
# heartbeat enqueues a BackgroundJob instead of doing the work directly.  A
# separate worker process (python -m app.worker) claims and executes those
# jobs via SELECT FOR UPDATE SKIP LOCKED — safe for Postgres + multiple
# workers.  This keeps the single-process path untouched while allowing
# horizontal scaling when needed.
# ---------------------------------------------------------------------------
mind = MindLoop(get_provider())
mote = MoteLoop()
reminders = ReminderLoop()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    if settings.environment == "production":
        missing = []
        if not settings.jwt_access_token_secret or len(settings.jwt_access_token_secret) < 32:
            missing.append("JWT_ACCESS_TOKEN_TTL_MINUTES secret (must be >= 32 chars)")
        if not settings.database_url and not settings.is_sqlite:
            missing.append("DATABASE_URL_OVERRIDE (Postgres connection string)")
        if settings.ai_provider == "gemini" and not settings.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if settings.ai_provider == "ollama" and not settings.ollama_host:
            missing.append("OLLAMA_HOST")
        if missing:
            logger.critical("production startup aborted — missing: %s", ", ".join(missing))
            raise SystemExit(f"missing required production config: {', '.join(missing)}")

    try:
        if settings.is_sqlite:
            # The native no-Docker setup: sqlite has no alembic migration chain
            # (they target postgres), so the schema is created directly. Safe
            # on every boot: create_all only adds missing tables.
            import app.models  # noqa: F401  (register models on Base.metadata)

            Base.metadata.create_all(engine)
            logger.info("sqlite schema ready")
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
    if settings.perception_enabled and not settings.worker_mode:
        mind.start()
        logger.info("mind loop started (heartbeat=%ss)", settings.mind_heartbeat_seconds)
    if settings.mote_enabled and not settings.worker_mode:
        mote.start()
        logger.info("mote started (heartbeat=%ss, quiet-after=%ss)", settings.mote_heartbeat_seconds, settings.mote_quiet_after_seconds)
    if settings.reminders_enabled and not settings.worker_mode:
        reminders.start()
        logger.info("reminders started (heartbeat=%ss)", settings.reminder_heartbeat_seconds)
    if settings.tts_enabled:
        # Warm the kokoro pipeline off the request path: the first synthesis
        # pays the model-load cost (~9s), which would otherwise hit the first
        # reply and make her seem slow to speak. Fire-and-forget in a thread so
        # startup stays fast.
        import threading

        threading.Thread(target=_warm_tts, daemon=True).start()
        logger.info("tts pipeline warming in background")

    # Ambient weather is fetched off the request path too, so the very first
    # reply already knows what the sky is doing instead of paying a network
    # round-trip inside the first message.
    warm_weather()

    yield
    _shutdown_loops()


def _warm_tts() -> None:
    try:
        from app.services.speech.service import synthesize

        synthesize("Hello.")
        logger.info("tts pipeline ready")
    except Exception as exc:  # pragma: no cover - warming must never crash boot
        logger.warning("tts warm-up failed (first synthesis may be slow): %s", exc)


def _shutdown_loops() -> None:
    mind.stop()
    mote.stop()
    reminders.stop()


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
    app.add_middleware(RateLimitMiddleware)

    # The API lives at the root (what the desktop companion, host scripts, and
    # the tunnel's nginx already use) AND under /api — what the web bundle
    # fetches (nginx used to strip that prefix). Serving both means the backend
    # can stand alone on one port with no proxy in front.
    app.include_router(api_router)
    if settings.is_sqlite:
        # Native single-port mode: the web bundle fetches /api/... (in docker
        # the nginx proxy stripped that prefix). Alias the router so the
        # backend can stand alone on one port with no proxy in front.
        app.include_router(api_router, prefix="/api")

    if not settings.is_sqlite:
        return app

    # Native single-port mode: serve the built web app from this process so
    # there is no separate web container. The SPA's deep links fall back to
    # index.html; unknown /api paths stay 404s rather than returning the page.
    from pathlib import Path

    from fastapi.responses import FileResponse, JSONResponse, Response

    static_dir = Path(os.environ.get("MIRA_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "ws/")):
            return JSONResponse({"detail": "not found"}, status_code=404)
        target = (static_dir / path).resolve()
        if static_dir.resolve() in target.parents and target.is_file():
            return FileResponse(target)
        index = static_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "web dist not built"}, status_code=404)

    return app


app = create_app()
