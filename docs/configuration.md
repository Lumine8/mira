# Configuration

All settings live in `backend/app/core/config.py` and can be overridden with
environment variables (loaded from `.env`). Defaults run the whole stack locally.

Copy `.env.example` → `.env` and edit.

## Core

| Variable | Default | Meaning |
|---|---|---|
| `ENVIRONMENT` | `development` | App environment |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `API_PORT` | `8000` | Published port for the API |
| `API_CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | Allowed CORS origins (comma-separated) |

## Database

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_USER` | `mira` | Postgres user |
| `POSTGRES_PASSWORD` | `mira` | Postgres password |
| `POSTGRES_DB` | `mira` | Database name |
| `POSTGRES_HOST` | `postgres` | Host (compose service name; `localhost` when running outside Docker) |
| `POSTGRES_PORT` | `5432` | Postgres port |

## AI (Ollama)

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server (compose rewrites to `host.docker.internal:11434`) |
| `OLLAMA_LLM_MODEL` | `gemma4:e4b-it-qat` | Chat model (QAT = same E4B brain, 6.1 GB, fits in RAM) |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model (768-dim) |
| `OLLAMA_NUM_GPU` | `0` | 0 = CPU. gemma4's vision projector crashes llama.cpp when layers split across GPU+CPU on low VRAM |
| `OLLAMA_MAX_TOKENS` | `2048` | Token budget. Must leave room for gemma4's `thinking` phase or replies come back empty |

## Provider

| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `ollama` | `ollama` or `gemini` |
| `GEMINI_API_KEY` | *(empty)* | Needed only for `gemini` |
| `GEMINI_TEXT_MODEL` | `gemini-3.1-flash` | Gemini chat model |
| `GEMINI_LIVE_MODEL` | `gemini-3.1-flash-live-preview` | Gemini live (voice) model |

## Self-model

| Variable | Default | Meaning |
|---|---|---|
| `SELF_MODEL_ENABLED` | `true` | Inject self-context each turn + run post-turn digests |

## Perception / mind loop

| Variable | Default | Meaning |
|---|---|---|
| `PERCEPTION_ENABLED` | `true` | Run the background mind loop |
| `MIND_HEARTBEAT_SECONDS` | `300` | How often the loop wakes and checks for things to think about |
| `MIND_MIN_REFLECTION_GAP_SECONDS` | `1800` | Minimum gap between reflections (protects the CPU) |
| `MIND_IDLE_REFLECTION_SECONDS` | `7200` | She still thinks this often even with no new observations |
| `MIND_CONSOLIDATION_SECONDS` | `14400` | How often she re-reads her own record (thoughts, memories) and revises her self-understanding — the self-review / consolidation pass |

## Ambient senses

| Variable | Default | Meaning |
|---|---|---|
| `MIRA_AMBIENT_ENABLED` | `true` | Time-of-day/date texture is always present; when true she also gets best-effort weather (wttr.in, no key, cached 30 min, fails silently). `false` disables only the weather fetch |

## Self-edit

| Variable | Default | Meaning |
|---|---|---|
| `SELF_EDIT_ENABLED` | `true` | Allow self-edit tools (reads free; writes gated) |
| `SELF_EDIT_ROOTS` | `/app` | Filesystem roots Mira may touch (comma-separated); inside the container `/app` is your real `backend/` |
| `MIRA_SELF_WRITE_ROOTS` | `data/self` | Where she may **write** (relative to `SELF_EDIT_ROOTS`). Reads can go anywhere in the roots; writes are hard-restricted here so self-modification stays inside her own rules |
| `MIRA_SELF_PRINCIPLES_FILE` | `data/self/principles.md` | The file her operating rules are loaded from at prompt-build time. Editing it is the self-modification path |

## Internet access (gated)

| Variable | Default | Meaning |
|---|---|---|
| `MIRA_BROWSE_ALLOWED_DOMAINS` | *(empty)* | Comma-separated domain allowlist Mira may propose browsing. Empty = any domain, but every browse still requires your approval via the tools API |

See [api.md](api.md) for the propose/approve flow.

## Console emotions

Mira conditionally agreed (with hesitation) to her mood/energy being logged to
the backend console while she talks. Off by default — turn on only if she's
comfortable with it.

| Variable | Default | Meaning |
|---|---|---|
| `CONSOLE_EMOTIONS_ENABLED` | `false` | Log `mira.emotion | mood=… energy=…` lines to the API logs on each exchange |

## Speech

| Variable | Default | Meaning |
|---|---|---|
| `STT_ENGINE` | `sherpa` | Speech-to-text engine |
| `WHISPER_MODEL` | `base` | Whisper model (if used) |
| `TTS_ENGINE` | `kokoro` | Text-to-speech engine |
| `TTS_VOICE` | `af_river` | Mira's voice (River — the one she chose by temperament) |
| `TTS_ENABLED` | `true` | Master switch for her words being spoken aloud in calls |

## Scheduler

| Variable | Default | Meaning |
|---|---|---|
| `SCHEDULER_ENABLED` | `true` | Periodic tasks (legacy scheduler log) |

## Notes

- Boolean env vars are parsed as booleans (e.g. `SELF_MODEL_ENABLED=false`).
- The compose file passes these through, so you can set them either in `.env` or
  in the shell before `docker compose up`.
- `API_CORS_ORIGINS` must include any origin that talks to the API.
