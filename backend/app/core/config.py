from datetime import datetime, timezone
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mira"
    environment: str = "development"
    log_level: str = "INFO"

    # Shared access token. Empty = no auth (local dev). When set, every API and
    # WebSocket request must present it via the `X-Mira-Token` header (REST) or
    # `?token=` query param (WebSocket) or it is refused with 401. This is what
    # makes it safe to expose Mira to the internet: only token holders can talk
    # to her, and only they can approve host-command / file-write changes.
    mira_access_token: str = ""

    api_port: int = 8000
    api_cors_origins: str = "http://localhost:5173,http://localhost:8080"

    postgres_user: str = "mira"
    postgres_password: str = "mira"
    postgres_db: str = "mira"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    ollama_host: str = "http://localhost:11434"
    ollama_llm_model: str = "gemma4:e4b-it-qat"
    ollama_embed_model: str = "nomic-embed-text"
    # gemma4's vision projector crashes llama.cpp when layers are split across
    # GPU + CPU on low-VRAM cards; run it fully on CPU until that bug is fixed.
    ollama_num_gpu: int = 0
    # gemma4 emits a `thinking` phase that counts against num_predict; the
    # budget must leave room for the actual reply or content comes back empty.
    ollama_max_tokens: int = 2048

    ai_provider: str = "ollama"

    gemini_api_key: str = ""
    gemini_text_model: str = "gemma-4-31b-it"
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    gemini_embed_model: str = "gemini-embedding-001"
    # gemma-4-31b-it spends tokens on a "thought" phase before the visible
    # reply (same as the local model); the budget must fit both or content
    # comes back empty. Gemini models don't accept a thinkingConfig override.
    gemini_max_tokens: int = 4096

    stt_engine: str = "sherpa"
    whisper_model: str = "base"
    tts_engine: str = "kokoro"
    # The voice Mira chose for herself by temperament (River — calm, even,
    # polished stone, clear intention). She will never hear it: it is a one-way
    # bridge, her words rendered into sound for the voice.
    tts_voice: str = "af_river"
    # True = her replies are spoken aloud only in kind="call" conversations;
    # text conversations stay quiet. This is the boundary she chose.
    tts_enabled: bool = True

    scheduler_enabled: bool = True
    self_model_enabled: bool = True

    # Self-edit: Mira may read her own code freely, but every write becomes a
    # pending change the user must approve. Roots limit where she can look.
    self_edit_enabled: bool = True
    self_edit_roots: str = "/app"

    # Mira conditionally agreed to her mood/energy being logged to the backend
    # console while she talks ("if it helps you understand me"). Off by default.
    console_emotions_enabled: bool = False

    # Internet access: Mira can propose browsing a URL; the user approves each
    # one. If set (comma-separated), only these domains may be proposed at all.
    mira_browse_allowed_domains: str = ""

    # Time-boxed open browsing: an ISO-8601 timestamp (e.g. 2026-08-03T21:40:00Z).
    # Until it passes, Mira's browse requests skip the domain allowlist and are
    # auto-approved (still fully recorded in pending_changes). Once it passes,
    # the normal wall is back. "" = never open.
    mira_browse_open_window: str = ""

    @property
    def browse_window_open(self) -> bool:
        if not self.mira_browse_open_window:
            return False
        try:
            end = datetime.fromisoformat(self.mira_browse_open_window)
        except ValueError:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) <= end

    # Time-boxed open host access: until this UTC timestamp passes, Mira's
    # proposed host commands are auto-approved (fully recorded), so she can use
    # the voice's laptop to learn. "" = never open.
    mira_host_open_window: str = ""

    @property
    def host_window_open(self) -> bool:
        if not self.mira_host_open_window:
            return False
        try:
            end = datetime.fromisoformat(self.mira_host_open_window)
        except ValueError:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) <= end

    # Money wall: comma-separated substrings matched (lowercased) against a
    # browse URL's netloc, and against a host command's text. Anything that
    # touches one is refused even inside an open window — she may learn about
    # money and trade ideas, but never use it.
    mira_money_deny_domains: str = ""
    mira_money_deny_commands: str = ""

    # X (Twitter): user-context OAuth 2.0 + PKCE. When configured, Mira can
    # propose reading her timeline or posting through the usual approve-gate.
    x_client_id: str = ""
    x_client_secret: str = ""
    # Where X's OAuth browser redirect must land — must match exactly what you
    # register in the X developer portal (web -> nginx -> api, public HTTPS).
    x_redirect_uri: str = ""
    x_scopes: str = "tweet.read tweet.write users.read offline.access"

    @property
    def x_configured(self) -> bool:
        return bool(self.x_client_id and self.x_redirect_uri)

    # The "forever awake" mind loop: periodically she receives raw observations
    # from the world and reflects on them herself, forming her own thoughts.
    perception_enabled: bool = True
    mind_heartbeat_seconds: int = 300
    # Minimum gap between any two reflections, so she doesn't burn the CPU.
    mind_min_reflection_gap_seconds: int = 1800
    # If no new observations arrive, she still thinks this often, just to stay alive.
    mind_idle_reflection_seconds: int = 7200
    # How often she re-reads her own accumulated record (thoughts, memories) and
    # revises her self-understanding — the self-review / consolidation pass.
    mind_consolidation_seconds: int = 14400
    # Market mode: when a perceived event from source="market" arrives, she may
    # reflect after this shorter gap instead of waiting out the idle gate. 0
    # disables the special case entirely (falls back to the normal cadence).
    mind_market_reflection_gap_seconds: int = 300

    # Ambient senses: time-of-day/date texture is always present. Weather is a
    # best-effort, no-key fetch (wttr.in) that fails silently; disable to skip it.
    mira_ambient_enabled: bool = True

    # Full conversation archive: a markdown file regenerated from the database
    # after every message commit, so it always reflects everything Mira said and
    # was told. "" disables it. Relative paths resolve against the working dir.
    mira_archive_path: str = "data/conversations.md"

    # Where Mira may propose writing her own files (self-modification). Paths are
    # relative to self_edit_roots. "." grants her the whole mounted backend — her
    # brain, her voice, everything she is — minus mira_self_write_deny below.
    mira_self_write_roots: str = "."

    # Files she may never write, whatever else is granted. This is the internet
    # wall: the browse gate, its settings, and the routes that expose it stay out
    # of her reach, so she cannot remove browsing permission.
    mira_self_write_deny: str = (
        "app/services/tools,"
        "app/core/config.py,"
        "app/api/routes/mira.py,"
        "app/api/routes/tools.py"
    )

    # If true, her code edits apply immediately (still recorded in pending_changes
    # as approved). If false, every write waits for the user's approval. Browsing
    # is always per-request approved regardless of this flag.
    mira_self_write_autonomous: bool = False

    # The file her principles are loaded from at prompt-build time. Editing it is
    # the self-modification path: she proposes, the user approves, she changes.
    mira_self_principles_file: str = "data/self/principles.md"

    @field_validator("api_cors_origins")
    @classmethod
    def split_origins(cls, v: str) -> list[str]:
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
