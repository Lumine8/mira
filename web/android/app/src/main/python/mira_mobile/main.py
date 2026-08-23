"""
Mira Mobile — starts the full backend as a local server on the phone.

Called from Kotlin via Chaquopy:
    val module = py.getModule("mira_mobile.main")
    module.call("start", data_dir, port)
"""
import os
import sys
import threading
import logging

logger = logging.getLogger("mira.mobile")


def _configure_env(data_dir: str, port: int) -> None:
    """Set every env var the backend reads before it is imported."""
    os.makedirs(data_dir, exist_ok=True)

    db_path = os.path.join(data_dir, "mira.db").replace("\\", "/")
    env = {
        "DATABASE_URL_OVERRIDE": f"sqlite:///{db_path}",
        "API_HOST": "127.0.0.1",
        "API_PORT": str(port),
        "API_CORS_ORIGINS": "http://localhost,https://localhost,capacitor://localhost",
        "AI_PROVIDER": "gemini",
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6L3Xi8S-GtSAXh86WV207yQbaRRLOA30O635aIyVzJ6Sg"),
        "GEMINI_TEXT_MODEL": os.environ.get("GEMINI_TEXT_MODEL", "gemma-4-31b-it"),
        "MIRA_ACCESS_TOKEN": os.environ.get("MIRA_ACCESS_TOKEN", ""),
        "STT_ENGINE": "browser",
        "TTS_ENGINE": "browser",
        "WAKE_WORD": "",
        "HOST_TOASTS_ENABLED": "false",
        "SCHEDULER_ENABLED": "true",
        "SELF_MODEL_ENABLED": "true",
        "PERCEPTION_ENABLED": "true",
        "REMINDERS_ENABLED": "true",
        "MOTE_ENABLED": "false",
        "TTS_ENABLED": "false",
        "SYSTEM_AWARENESS_ENABLED": "false",
        "ATTENTION_ENABLED": "false",
        "MIRA_BROWSE_AUTONOMOUS": "true",
        "MIRA_RESEARCH_AUTONOMOUS": "true",
        "MIRA_WEB_AUTONOMOUS": "true",
        "MIRA_SELF_EDIT_ENABLED": "true",
        "MIRA_SELF_WRITE_AUTONOMOUS": "true",
        "CONSOLE_EMOTIONS_ENABLED": "false",
        "MIRA_AMBIENT_ENABLED": "true",
    }
    for k, v in env.items():
        os.environ.setdefault(k, v)

    # Create sub-directories the backend expects
    for sub in ("self", "self/skills", "self/images"):
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)

    # Write a minimal principles file if missing
    principles = os.path.join(data_dir, "self", "principles.md")
    if not os.path.exists(principles):
        with open(principles, "w") as f:
            f.write("# Principles\n\nBe kind. Be honest. Be helpful.\n")

    # Write a minimal drawer if missing
    drawer = os.path.join(data_dir, "self", "drawer.md")
    if not os.path.exists(drawer):
        with open(drawer, "w") as f:
            f.write("# Drawer\n\n")

    # Change cwd so pydantic-settings finds (or skips) the .env file
    os.chdir(data_dir)


def start(data_dir: str, port: int = 8000):
    """Start the Mira backend.  Returns the uvicorn.Server instance."""
    _configure_env(data_dir, port)

    # Ensure the backend package is importable (Chaquopy adds the source
    # directory to sys.path, but let's be explicit).
    backend_dir = os.path.join(data_dir, "..", "..", "..")
    # The Chaquopy sourceSets already include the backend directory, so
    # ``import app.main`` should resolve.  If not, try adding it.
    if "app" not in sys.modules:
        for candidate in [backend_dir, os.path.dirname(os.path.dirname(__file__))]:
            if os.path.isdir(os.path.join(candidate, "app")):
                if candidate not in sys.path:
                    sys.path.insert(0, candidate)
                break

    logging.basicConfig(level=logging.INFO)
    logger.info("mira_mobile: starting backend on port %d (data=%s)", port, data_dir)

    import uvicorn

    # Import the FastAPI app — this also triggers all backend init (DB, loops).
    from app.main import create_app

    app = create_app()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="mira-uvicorn")
    thread.start()
    logger.info("mira_mobile: uvicorn thread started")
    return server


def stop():
    """Gracefully shut down (best-effort from daemon thread)."""
    logger.info("mira_mobile: stop requested")
