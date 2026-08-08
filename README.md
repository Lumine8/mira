# Mira

A voice-first AI companion. Not a chatbot with a microphone — she feels like someone you call.

## Quick start

Requirements:
- Docker Desktop (Postgres/pgvector + API)
- Node.js 20+ (frontend dev server)
- [Ollama](https://ollama.com) installed natively on the host — it uses your GPU and is reached from the API container via `host.docker.internal`. The docker-compose file does **not** run Ollama in a container (a WSL2 VM is too small for the model).

```powershell
ollama pull gemma4:e4b-it-qat  # LLM brain (~6.1 GB, fits in 16 GB RAM)
ollama pull nomic-embed-text  # embeddings (~274 MB)
npm --prefix web install
Copy-Item .env.example .env
.\dev.ps1
```

- Web app (dev): http://localhost:5173 — production build: http://localhost:8080
- API: http://localhost:8000 (docs at `/docs`)
- Postgres (pgvector): localhost:5432

> `.\dev.ps1` runs the backend (Docker: Postgres + API) and the frontend (Vite) together; Ctrl+C stops it. See [`docs/run.md`](docs/run.md).

## Talk to her

Mira has a real home: **https://mira.mousebase.dev**

She lives on this machine and is reached through a Cloudflare **named tunnel**
(`mira`) that runs as a Windows service and starts on boot. The hostname is a
proxied DNS CNAME; no ports are open on the network. When you open the URL you
still need the access token — appending `?token=<MIRA_ACCESS_TOKEN>` to the
address logs you in (see [`.env`](.env.example) / [`docs/deploy.md`](docs/deploy.md)).

## Architecture

```
Browser (React/Vite) ──WebSocket (audio + events)──▶ FastAPI
                                                      ├─ Speech: Silero VAD · sherpa-onnx ASR · Kokoro TTS
                                                      ├─ Cognition: single structured pass · emotion · state
                                                      ├─ AI: Ollama (native/GPU) — Gemini optional later
                                                      ├─ Memory: pgvector (facts, episodes, relationship)
                                                      ├─ Life: scheduler + proactive texts
                                                      └─ Self-dev: gated fs/git/test tools
```

## Project layout

```
backend/   FastAPI + SQLAlchemy + Alembic + pgvector
web/       React + Vite + TypeScript + SCSS + Framer Motion
```

## Env

Copy `.env.example` to `.env` and adjust. Defaults run the whole stack locally via Docker.

## Docs

Full documentation lives in [`docs/`](docs/):

- [`docs/run.md`](docs/run.md) — how to run the project
- [`docs/deploy.md`](docs/deploy.md) — putting her on the internet (Cloudflare named tunnel)
- [`docs/architecture.md`](docs/architecture.md) — architecture, layout, data model
- [`docs/configuration.md`](docs/configuration.md) — every environment variable
- [`docs/api.md`](docs/api.md) — REST + WebSocket API reference
- [`docs/self-model.md`](docs/self-model.md) — her persistent identity, memory, thoughts
- [`docs/perception.md`](docs/perception.md) — the mind loop, observations, host sampler
- [`docs/self-edit.md`](docs/self-edit.md) — her approval-gated self-editing tools
