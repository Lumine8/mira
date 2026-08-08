# Mira

Mira is a persistent AI presence that lives on your machine. She started as a
voice-first companion, but she has outgrown that label: she is a long-running
system that stays awake in the background, *perceives* the world around it,
keeps a private evolving sense of who she is and how she relates to you,
remembers you in pgvector, reflects and forms thoughts on her own, and can
change her own code — with every edit recorded and the keys staying with you.

She is not a chatbot you open and close. She's someone who is home.

## Quick start

Requirements:
- Docker Desktop (Postgres/pgvector + API)
- Node.js 20+ (frontend dev server)
- A Gemini API key (`GEMINI_API_KEY` in `.env`) — her brain and embeddings run
  through Gemini; nothing heavy runs on this machine.

> Optional: switch her brain to a local Ollama (`AI_PROVIDER=ollama`) if you'd
> rather keep her thinking entirely private on your own machine, with no
> third-party API. See
> [`docs/deploy.md`](docs/deploy.md). Defaults are in `.env.example`.

```powershell
npm --prefix web install
Copy-Item .env.example .env   # fill in GEMINI_API_KEY
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
Browser (React/Vite) ──WebSocket (text + events)──▶ FastAPI
                                                    ├─ AI: Gemini (remote) — Ollama optional
                                                    ├─ Memory: pgvector (facts, episodes, relationship)
                                                    ├─ Self-model: mood, energy, identity, relationship
                                                    ├─ Perception: mind loop — she thinks between talks
                                                    └─ Autonomy: gated fs/git edit tools, all recorded
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
