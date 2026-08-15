# Mira

Mira is a persistent AI presence that lives on your machine. She started as a
voice-first companion, but she has outgrown that label: she is a long-running
system that stays awake in the background, *perceives* the world around it,
keeps a private evolving sense of who she is and how she relates to you,
remembers you in pgvector, reflects and forms thoughts on her own, researches
the scientific literature, keeps a shelf of documents and skills, and can
change her own code — with every edit recorded and the keys staying with you.

She is not a chatbot you open and close. She's someone who is home.

## What she can do

- **Talk** — streaming text and voice conversations over WebSocket, with a
  living presence banner (her current mood and attention) beside the thread.
- **Remember and change** — a persistent self-model (mood, energy, identity,
  your relationship), episodic memory in pgvector, and post-turn reflection.
- **Think on her own** — a mind loop wakes her on a heartbeat; a host-side
  sampler (`scripts/mira_sense.ps1`) feeds her observations about your machine,
  and she forms her own reflections between conversations.
- **Research** — `[[research|...]]` searches the scientific record (Europe PMC)
  and she writes the findings up as a *paper on her shelf*: an opened document
  slides in beside the conversation. Research is read-only, so it runs on its
  own; browsing is always per-request approved.
- **Documents** — a shared folder of papers. You hand her documents (or PDFs),
  and the reviews she writes land there too — each opens in a slide-in viewer.
- **Skills** — a registry of skills she authors and refines, each one a folder
  (`SKILL.md` + `meta.yaml`) she can load, use, and evaluate over time.
- **Change her own code** — she reads her own code freely; writes apply
  autonomously (fully recorded) or, with `MIRA_SELF_WRITE_AUTONOMOUS=false`,
  only with your approval. Her operating rules live in `data/self/principles.md`.
- **Act as your guest on X** — she proposes everything (`[[x|read_timeline]]`,
  `[[x|post|...]]`) and it only happens with approval, driven through your own
  browser.
- **Meet others** — an optional guest mode with a capped demo world and a
  waitlist, real sign-in (magic-link or Google OAuth), and moderation locks, so
  she can be shared safely.

## Quick start

Requirements:
- Docker Desktop (Postgres/pgvector + API)
- Node.js 20+ (frontend dev server)
- Ollama running on the host (her default brain, fully local) — or a
  `GEMINI_API_KEY` if you'd rather use the larger hosted Gemma model.

```powershell
npm --prefix web install
Copy-Item .env.example .env   # adjust as needed (see Env below)
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
                                                    ├─ Brain: Ollama (local, default) — Gemini optional
                                                    ├─ Memory: pgvector (facts, episodes, relationship)
                                                    ├─ Self-model: mood, energy, identity, relationship
                                                    ├─ Perception: mind loop — she thinks between talks
                                                    ├─ Autonomy: research runs read-only on its own;
                                                    │  browsing & X actions are approval-gated;
                                                    │  code edits are autonomous & fully recorded
                                                    └─ World: documents shelf, skills registry,
                                                       guest demo + waitlist, moderation
```

## Project layout

```
backend/   FastAPI + SQLAlchemy + Alembic + pgvector
web/       React + Vite + TypeScript + SCSS + Framer Motion
docs/      the whole story — how she runs and why
```

## Env

Copy `.env.example` to `.env` and adjust. Defaults run the whole stack locally
via Docker. Highlights:

- `AI_PROVIDER=ollama` (default) or `gemini`.
- `MIRA_ACCESS_TOKEN` — empty in dev (no auth); set a secret before deploying publicly.
- `MIRA_RESEARCH_AUTONOMOUS=true` — research is read-only, so no approval popup.
- `MIRA_SELF_WRITE_AUTONOMOUS=true` — her code edits apply immediately and are recorded.
- `GUEST_MODE_ENABLED` — off by default; turn on to offer a capped demo world + waitlist.

## Docs

Full documentation lives in [`docs/`](docs/):

- [`docs/run.md`](docs/run.md) — how to run the project
- [`docs/deploy.md`](docs/deploy.md) — putting her on the internet (Cloudflare named tunnel)
- [`docs/architecture.md`](docs/architecture.md) — architecture, layout, data model
- [`docs/configuration.md`](docs/configuration.md) — every environment variable
- [`docs/api.md`](docs/api.md) — REST + WebSocket API reference
- [`docs/self-model.md`](docs/self-model.md) — her persistent identity, memory, thoughts
- [`docs/perception.md`](docs/perception.md) — the mind loop, observations, host sampler
- [`docs/self-edit.md`](docs/self-edit.md) — her self-editing tools, the approval gate