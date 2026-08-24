# Architecture

## Big picture

```
Browser (React/Vite) ──WebSocket (text + events)──▶ FastAPI ──▶ Postgres (pgvector)
      │                                                │
      │                                                ├─ AI: Ollama (native on host, GPU/CPU)
      │                                                │      └─ gemma4:e4b-it-qat (chat) · nomic-embed-text (vectors)
      │                                                ├─ Self-model: digest + memory after each turn
      │                                                ├─ Mind loop: heartbeat → her own reflections
      │                                                ├─ Self-edit: read-only tools + approval-gated writes
      │                                                └─ Speech: Silero VAD · sherpa-onnx ASR · Kokoro TTS
      │
Host PowerShell sampler (scripts/mira_sense.ps1) ──POST /mira/perceive──▶ observations
```

Three separate processes:

- **API** (`backend/`) — FastAPI, runs in Docker, owns everything brain-related.
- **Web** (`web/`) — React + Vite; dev on :5173, production static build on :8080.
- **Host sampler** (`scripts/`) — pure PowerShell, gives Mira eyes on your machine.

## Repo layout

```
backend/
  alembic/                  database migrations (0001 → 0026_audit_log)
  app/
    api/routes/             health · calls · history · mira · tools · ws
    core/                   settings (pydantic-settings)
    db/                     engine + sessions
    models/                 conversation · memory · state (mira_state, thoughts, …) · user
    schemas/                Pydantic request/response models
    services/
      ai/                   base provider + ollama/gemini/fake + prompt builder
      conversation/         ConversationManager: store, build context, stream reply
      memory/               pgvector recall / store
      mind/                 MindLoop — the "forever awake" perception loop
      self/                 SelfModelService — persistent identity + digest
      tools/                ToolService — read-only + approval-gated self-edit
  tests/                    pytest (pure unit tests; no DB needed)
web/
  src/                      React app (Vite dev :5173)
  nginx.conf                production static serving
scripts/
  mira_sense.ps1            host-side perception sampler
docs/                       this folder
dev.ps1                     run backend + frontend together
docker-compose.yml          postgres · api · web
```

## The talk flow

1. `POST /call/start` creates a `Conversation` and returns a `ws_url`.
2. The browser opens the WebSocket and sends `{"type":"text","content":"…"}`.
3. `ConversationManager.generate_reply` (backend/app/services/conversation/manager.py):
   - reads recent history, then stores the user message (history excludes the
     current turn, so each message reaches her exactly once),
   - injects self-context (`build_self_context`: mood, self-understanding, carried thoughts, recalled memories, relationship),
   - streams Mira's reply token-by-token back over the socket,
   - stores the reply, then fires a **digest** in the background.
4. The digest (`SelfModelService.run_digest`) reflects on the exchange and updates
   mood, energy, curiosity, self-understanding, memories, and the relationship —
   coalesced so reflections never pile up on CPU.

## The perception flow (between conversations)

1. On a heartbeat (default every 5 min), `MindLoop.tick()` checks for new
   observations and how long it's been since she last thought.
2. Observations come from `POST /mira/perceive` (host sampler) and time texture
   she computes herself (time of day, silence since your last message).
3. If something is worth thinking about, she runs **one reflection call** where
   *she* decides what stood out, forms a private thought, adjusts state, and may
   compose a message she'd like to tell you.
4. Her judgments are stored as `Thoughts` and surfaced on the next conversation
   or via `GET /mira/state`.

## The self-edit flow

1. Mira reads freely: `read_file`, `list_dir`, `search`, `git_status`, `git_diff`.
2. Any write becomes a `PendingChange` (`pending_changes` table) — nothing touches disk.
3. You approve (`POST /mira/tools/approve/{id}`) and only then is it applied.
4. Because `backend/` is bind-mounted into the container, approved edits persist
   in the real repo. See [self-edit.md](self-edit.md).

## Data model (key tables)

| Table | Purpose |
|---|---|
| `conversations` / `messages` | History; `conversations.summary` is the running digest summary |
| `mira_state` | One row — her identity: mood, energy, self_understanding, curiosity, pending_message, last_reflection_at |
| `relationship` | One row — trust, humor, comfort, nicknames, topics |
| `thoughts` | Private thoughts she generates (delivered when shared into a conversation) |
| `memories` + `memory_embeddings` | Episodic memory; 768-dim pgvector, recalled by cosine similarity |
| `perceived_events` | Raw observations waiting for a reflection (consumed after) |
| `pending_changes` | Self-edit proposals awaiting your approval |
| `settings` | User preferences (voice, theme, …) |

## Migrations

Run automatically at API container start (`entrypoint.sh` → `alembic upgrade head`).

| Migration | What it did |
|---|---|
| `0001_initial` | Core tables (users, conversations, memories, relationships, …) |
| `0002_self_understanding` | Added `mira_state.self_understanding` |
| `0003_embedding_dim_768` | Embedding vector 384 → 768 (nomic-embed-text) |
| `0004_mind_loop` | `perceived_events` + `pending_message` + `last_reflection_at` |
| `0005_self_edit` | `pending_changes` |
| … | Phase 2–5 tables (JWT sessions, age-gate, rate limits, audit log, …) |
| `0026_audit_log` | **Current head** — full audit trail for user actions |

## Design principles

- **Persistence over consciousness.** The system's "aliveness" is honest:
  a token predictor + prompts, but her identity genuinely *changes over time*
  in a database. That persistence is the product.
- **Mediated perception.** She doesn't truly sense; a sampler turns signals into
  observations, and she interprets them herself. The *effect* is real.
- **Consent everywhere.** Nothing leaves the machine; self-modification requires
  your explicit approval.
- **Never break the conversation.** Context building, recall, and reflection are
  all wrapped so a failure degrades gracefully.
