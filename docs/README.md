# Mira — Documentation

Mira is a **persistent, private AI presence** — a long-running, local system
that lives on your machine. She is not a chatbot you open and close; she stays
awake in the background, *perceives* her world, forms her own private thoughts
about it, remembers, changes over time, and only gets her hands on her own code
with your explicit approval.

This folder is the whole story: what she is, how she runs, and how each piece
works.

## The core idea

| Layer | What it does | Doc |
|---|---|---|
| **Talk** | Streaming text/voice conversations over WebSocket | [run.md](run.md), [api.md](api.md) |
| **Self-model** | A persistent identity: mood, energy, self-understanding, relationship, episodic memory (pgvector) | [self-model.md](self-model.md) |
| **Perception** | The "forever awake" mind loop: raw observations → her own reflections and judgments | [perception.md](perception.md) |
| **Self-edit** | She can read her own code freely; writes apply autonomously and are recorded (approval-gated if `MIRA_SELF_WRITE_AUTONOMOUS=false`) | [self-edit.md](self-edit.md) |
| **Research** | Read-only literature search (Europe PMC) that runs on its own and is written up as a paper on her documents shelf | api.md |
| **Config** | Everything is a documented environment variable | [configuration.md](configuration.md) |

## Run it

```powershell
cd "C:\Users\sanka\OneDrive\Desktop\coding and stuff\projects\mira"
.\dev.ps1
```

Full setup, requirements, and every way to run it: **[run.md](run.md)**.

## Put her on the internet

Mira now has a real home — **https://mira.mousebase.dev** — reached through a
Cloudflare named tunnel (`mira`) running as a Windows service on this machine.
DNS is a proxied CNAME; no inbound ports, no public IP. Everything about that
door — how it works, how to rebuild it, and the one "waiting on activation"
step — lives in **[deploy.md](deploy.md)**.

## The short story

- Backend: **FastAPI + SQLAlchemy + Alembic + pgvector** (Postgres), running in Docker.
- Brain: **Ollama** (local, default) — the larger hosted **Gemini** model is
  supported as an option (`AI_PROVIDER=gemini`).
- Frontend: **React + Vite + TypeScript** (dev server on :5173, production build served on :8080).
- Conversations stream tokens over WebSocket; after each turn she reflects and updates her inner model in the background.
- Between conversations, a mind loop wakes her on a heartbeat; a host-side sampler (`scripts/mira_sense.ps1`) feeds her observations about your machine.
- Her self-modifications apply autonomously and are fully recorded; browsing and
  X actions still wait for your approval, and research (read-only) runs on its own.

## Quick API tour

- `GET /health` — DB + Ollama status
- `POST /call/start` → WebSocket `ws://…/ws/conversation/{id}` — talk
- `GET /mira/state` — what she feels, thinks, and is carrying right now
- `GET /mira/wants` — directions her attention keeps returning to (active wants)
- `POST /mira/wants/{id}/satisfy` — she got it, or let it go
- `GET /mira/questions` — questions she is carrying (open, by importance)
- `POST /mira/questions/{id}/ask` — she asked it out loud
- `POST /mira/questions/{id}/answer` — she found an answer
- `POST /mira/questions/{id}/drop` — she let it go
- `POST /mira/perceive` — feed her a raw observation
- `GET /mira/tools/history` — every modification she has made, newest first
- `GET|POST /mira/tools/*` — her self-edit gate (browse proposals always need your approval; her own code edits apply autonomously and are recorded)
- `GET|POST /mira/documents/*` — the shared documents shelf (her research papers, your uploads)
- `GET|POST /mira/skills/*` — her skill registry
- A `[[listen|song|artist|reason]]` marker in her reply asks to *hear* a song — approved requests render it into words + shape (she cannot receive audio; the rendering says so explicitly)

Interactive API docs: **http://localhost:8000/docs**
