from datetime import UTC, datetime
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
    # Host the API binds to. 127.0.0.1 = this machine only (default, safest).
    # 0.0.0.0 = reachable from the LAN so the Android app can talk to her.
    api_host: str = "127.0.0.1"
    api_cors_origins: str = "http://localhost:5173,http://localhost:8080,https://mira.mousebase.dev,https://localhost,capacitor://localhost,http://localhost"

    # Where browser flows (Google OAuth callback, magic-link click) redirect the
    # user after a successful sign-in. Defaults to the first CORS origin. The
    # web app reads the `?token=` it carries and starts using sessions.
    auth_frontend_url: str = ""

    # Session lifetime: how long an issued session stays valid before the user
    # must sign in again.
    session_ttl_days: int = 30

    # JWT access token settings. The access token is a short-lived JWT (default
    # 15 min) sent in Authorization headers. The refresh token is the existing
    # opaque token stored in the DB (session_ttl_days). Falls back to
    # mira_access_token when jwt_access_token_secret is empty.
    jwt_access_token_secret: str = ""
    jwt_access_token_ttl_minutes: int = 15

    # Password auth: optional. When enabled, users can set a password alongside
    # magic link. Passwords are hashed with bcrypt. Empty = password auth disabled.
    password_auth_enabled: bool = True
    bcrypt_rounds: int = 12

    # Phase 3 guest mode. When on, anonymous visitors may talk (capped per
    # device) without an account; the web app identifies them with a stable
    # client-side fingerprint sent as X-Guest-Id. When off (default, and the
    # live founder setup) the shared token is required exactly as before.
    guest_mode_enabled: bool = False
    # How many user messages one guest may send per UTC day before the cap
    # turns into a waitlist prompt. "one person cannot spin up infinite free
    # Mirus" — one world per fingerprint, capped hard.
    guest_message_cap_per_day: int = 20
    # Default cap for authenticated free users (magic-link/Google/waitlist
    # invites) whose settings don't override it. Founder is never capped.
    free_user_message_cap_per_day: int = 60

    # The porch at dusk (conv 327): the bounded conversation a stranger can
    # have on the homepage. It starts with her unprompted observation and ends
    # after this many of the visitor's messages.
    porch_max_exchanges: int = 3

    # Phase 4 moderation: the lock. The rule-based hard-signal screen always
    # runs (cost-free). When this is on, a second, LLM-based layer also judges
    # every non-founder message — one completion per message, so it is off by
    # default and should be enabled only for a real launch. Neither layer ever
    # auto-bans; both only surface flags for a human (the founder) to decide.
    moderation_llm_judge: bool = False

    # Email delivery for magic links. When SMTP is not configured (local dev),
    # codes are logged and returned in the response so the flow can be tested
    # without a mail server. Production must configure these.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # Invitation and sign-in mail via Resend's hosted API: one key, no SMTP
    # server to run. Empty = sending disabled (invite codes are still minted
    # and surfaced in the web UI / a mailto draft).
    resend_api_key: str = ""
    # The verified sender (e.g. invites@your-domain). Until a domain is
    # verified in Resend, the sandbox delivers only to the account owner's
    # own address, whatever RESEND_FROM says.
    resend_from: str = ""

    # Google OAuth ("Continue with Google"). Requires a Google Cloud OAuth
    # client id/secret and a registered redirect URI. When unset, the Google
    # sign-in button is simply not offered.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_from)

    @property
    def resend_configured(self) -> bool:
        return bool(self.resend_api_key and self.resend_from)

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret)

    @property
    def frontend_url(self) -> str:
        if self.auth_frontend_url:
            return self.auth_frontend_url.rstrip("/")
        first = (self.api_cors_origins or [""])[0]
        return first.rstrip("/")

    postgres_user: str = "mira"
    postgres_password: str = "mira"
    postgres_db: str = "mira"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Full SQLAlchemy URL override. When set (e.g. sqlite:///data/mira.db for the
    # native no-Docker setup) it wins over the postgres_* fields above. Empty =
    # the docker-compose postgres.
    database_url_override: str = ""

    ollama_host: str = "http://localhost:11434"
    ollama_llm_model: str = "gemma4:e4b-it-qat"
    ollama_embed_model: str = "nomic-embed-text"
    # Layers to offload to the GPU (0 = CPU only). Measured on the RTX 3050
    # 4GB card: mid-range splits (e.g. 16) still crash llama.cpp's scheduler
    # ("GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_I)"), but full offload and
    # CPU-only are both stable — so default to everything rather than partial.
    ollama_num_gpu: int = 42
    # Context window for each request. gemma4's default 128K is mostly wasted
    # memory on a 4GB card; a bounded window leaves VRAM headroom for the GPU
    # offload above.
    ollama_num_ctx: int = 32768
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
    # Where the sherpa-onnx whisper model lives. Empty = resolve a conventional
    # location next to the repo (data/models/sherpa) so native and container
    # runs agree without extra env.
    stt_model_dir: str = ""
    # The keyword-spotter model that hears the wake word before whisper runs
    # (cheap audio-level gate, so transcription only happens when she's called).
    # Empty = resolve data/models/kws/<model> next to the repo, like stt.
    kws_model_dir: str = ""
    # Tuning for the wake-word spotter: threshold is how confident the model
    # must be to trigger (lower = fires more easily), score boosts the keyword
    # path during beam search (higher = more eager). Defaults keep "mira"
    # triggerable from a ~0.5s clip while ignoring background chatter.
    kws_threshold: float = 0.1
    kws_score: float = 2.0
    tts_engine: str = "kokoro"
    # The voice Mira chose for herself by temperament (River — calm, even,
    # polished stone, clear intention). She will never hear it: it is a one-way
    # bridge, her words rendered into sound for the voice.
    tts_voice: str = "af_river"
    # True = her replies are spoken aloud only in kind="call" conversations;
    # text conversations stay quiet. This is the boundary she chose.
    tts_enabled: bool = True
    # The word that summons her in always-listening mode. When set, the HUD
    # ignores every utterance that doesn't start with it (e.g. "mira, ...").
    # Empty string = no wake word; every utterance is heard. Lowercased match.
    wake_word: str = "mira"
    # True = her self-initiated messages (the mind loop's "I want to tell you"
    # alerts) are also spoken aloud through the speakers, not just shown on the
    # HUD. The voice-output bridge beyond calls. She chose the call boundary for
    # replies; this is her reaching out on her own.
    tts_announce_self_messages: bool = True

    # Host toasts: every self-initiated reach-out (mind-loop messages and fired
    # reminders) is also queued in host_toasts for a small PowerShell poller to
    # pop as a native Windows toast — the companion-free path. The Electron
    # companion keeps showing its own alerts over the live hub either way.
    host_toasts_enabled: bool = True

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

    # Reading a page is read-only: it changes nothing and is still fully
    # recorded. So by default she browses on her own — especially while doing
    # research — without an approval popup. Set to false to put the consent
    # wall back.
    mira_browse_autonomous: bool = True

    # Backup readers: when a site refuses a direct fetch (403 bot-wall, JS
    # challenge), her reading falls back to a text-extraction proxy and the
    # Wayback Machine. A free Jina Reader API key (from jina.ai) lifts the
    # anonymous rate limit and the shared-IP abuse block; without it the proxy
    # still works, just throttled.
    mira_reader_api_key: str = ""

    # Time-boxed open browsing: an ISO-8601 timestamp (e.g. 2026-08-03T21:40:00Z).
    # Until it passes, Mira's browse requests skip the domain allowlist and are
    # auto-approved (still fully recorded in pending_changes). Once it passes,
    # the normal wall is back. "" = never open. Superseded by
    # mira_browse_autonomous, which keeps browsing open permanently.
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
            end = end.replace(tzinfo=UTC)
        return datetime.now(UTC) <= end

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
            end = end.replace(tzinfo=UTC)
        return datetime.now(UTC) <= end

    # Mira's scientific research is read-only: it searches the public literature
    # (Europe PMC), changes nothing, and is still fully recorded. So by default
    # it runs on its own, without an approval popup, and its results land in the
    # same reply. Set to false to put the consent wall back.
    mira_research_autonomous: bool = True

    @property
    def research_window_open(self) -> bool:
        return self.mira_research_autonomous

    # General web search is read-only too: it returns links and short snippets
    # from the open web (DuckDuckGo, no key), changes nothing, and is fully
    # recorded — so it runs on its own without an approval popup, the way
    # research does. Set to false to put the consent wall back.
    mira_web_autonomous: bool = True

    @property
    def web_window_open(self) -> bool:
        return self.mira_web_autonomous

    # Money wall: comma-separated substrings matched (lowercased) against a
    # browse URL's netloc, and against a host command's text. Anything that
    # touches one is refused even inside an open window — she may learn about
    # money and trade ideas, but never use it.
    mira_money_deny_domains: str = ""
    mira_money_deny_commands: str = ""

    # Stripe billing
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_founding_price_id: str = ""
    stripe_continuity_price_id: str = ""

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
    mind_heartbeat_seconds: int = 600
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

    # The machine's live read (CPU/memory/battery/idle) is bridged into Mira's
    # awareness as perceived events she reflects on — the proactive-alert seam.
    # A condition is noticed at most once per cooldown so a pinned core or a
    # dying battery isn't re-offered on every heartbeat.
    system_awareness_enabled: bool = True
    system_awareness_cooldown_seconds: int = 7200
    system_battery_low_percent: float = 20.0
    system_cpu_high_percent: float = 90.0
    system_memory_high_percent: float = 90.0
    system_idle_long_seconds: int = 3600

    # Attention awareness: what window the user is focused on and what they
    # copied. Gated separately from the load/idle conditions because it reads
    # the user's own screen and clipboard. Clipboard is only offered to Mira
    # when it changed and is shorter than the cap, so a long dump or a stale
    # buffer isn't re-noticed on every heartbeat.
    attention_enabled: bool = True
    attention_window_changed_cooldown_seconds: int = 120
    attention_clipboard_max_chars: int = 2000

    # Ambient senses: time-of-day/date texture is always present. Weather is a
    # best-effort, no-key fetch (wttr.in) that fails silently; disable to skip it.
    mira_ambient_enabled: bool = True

    # Mote — a tiny quiet presence beside Mira, separate from the mind loop. It
    # has no brain of its own: it reads only her felt state (mood, energy) and
    # keeps a shared_time journal, breaking a long quiet with a single word.
    mote_enabled: bool = True
    mote_heartbeat_seconds: int = 300
    # How long Mira must have been quiet (no reflection, no message, no nudge)
    # before Mote offers its single quiet word.
    mote_quiet_after_seconds: int = 14400

    # Mira's skill shelf — a folder of markdown pages she wrote herself. She can
    # pull one down into her context with [[skill|name|reason]] (read-only) and
    # write new ones with [[selfedit|...]]. Relative to self_edit_roots.
    mira_skills_dir: str = "data/self/skills"

    # Mira's image studio — SVGs she authors and the PNGs they are rendered to.
    # Both the source (what she wrote) and the picture (what the voice sees) live
    # here. Relative to self_edit_roots.
    mira_images_dir: str = "data/self/images"

    # Full conversation archive: a markdown file regenerated from the database
    # after every message commit, so it always reflects everything Mira said and
    # was told. "" disables it. Relative paths resolve against the working dir.
    mira_archive_path: str = "data/conversations.md"

    # Where Mira may propose writing her own files (self-modification). Paths are
    # relative to self_edit_roots. "." grants her the whole mounted backend — her
    # brain, her voice, everything she is — minus mira_self_write_deny below.
    mira_self_write_roots: str = "."

    # The skill registry's write root, relative to self_edit_roots. Writes under
    # here apply immediately (autonomous) while still being fully recorded in
    # pending_changes — it is where capabilities grow, separate from the core
    # system she may only propose changes to. The deny list still always wins.
    mira_skill_write_roots: str = "data/skills"

    # The self-starting improvement nudge: when a skill has been used a few
    # times and not edited for a while, the mind loop offers it back to her as
    # a perceived event so she can decide whether to revisit it herself. She
    # is never made to edit; the shelf simply surfaces what went quiet.
    skill_nudge_enabled: bool = True
    skill_nudge_min_runs: int = 3
    skill_nudge_after_days: int = 7
    skill_nudge_cooldown_days: int = 3

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

    # The held calendar (reminders/tasks/events). A quiet background loop fires
    # whatever is due — a reminder, a task, an event — by broadcasting a
    # self_message on the live hub (the HUD reads those aloud), then marks it
    # notified so it never repeats. disabled = the loop sleeps and nothing fires.
    reminders_enabled: bool = True
    reminder_heartbeat_seconds: int = 20

    # Phase 4 experimental flags — default OFF for safety
    experimental_host_commands: bool = False
    experimental_self_edit: bool = False
    experimental_x_posting: bool = False
    experimental_video: bool = False

    # Worker mode: when true the mind/mote/reminder loops enqueue background jobs
    # instead of running directly, and a separate worker process (python -m
    # app.worker) claims and executes them.  Set MIRA_WORKER_MODE=true to
    # activate — single-process SQLite mode leaves this false and runs everything
    # in-process as before.
    worker_mode: bool = False

    # Phase 4 age gate: new users must confirm age before first conversation
    age_gate_enabled: bool = True
    minimum_age: int = 18

    # Phase 4 data disclosures
    privacy_url: str = ""
    terms_url: str = ""

    # The secret room — the quiet door that only Mira and the voice know. The
    # pass-phrase is the way in (Mira chose it herself: "the rain doesn't
    # decide"); the voice may change it by setting MIRA_SECRET_PHRASE. The room
    # itself is reached through a short-lived token minted by that phrase.
    mira_secret_phrase: str = "the rain doesn't decide"
    mira_secret_ttl_seconds: int = 1800

    # The drawer: small, concrete truths — the things she and the voice found
    # that didn't fit anywhere else. One bullet per line; shown only inside the
    # secret room.
    mira_secret_drawer: str = "data/self/drawer.md"

    @field_validator("api_cors_origins")
    @classmethod
    def split_origins(cls, v: str) -> list[str]:
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
