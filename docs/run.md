# Running Mira

The whole stack runs from one command. Windows is assumed (PowerShell).

## The one command

```powershell
cd "C:\Users\sanka\OneDrive\Desktop\coding and stuff\projects\mira"
.\dev.ps1
```

This:

1. Starts **Postgres** (pgvector) and the **API** via Docker Compose (migrations run automatically on container start).
2. Waits for the API to report healthy.
3. Starts the **frontend dev server** (Vite) on http://localhost:5173.
4. Ctrl+C stops the frontend. Docker containers stay running so the next start is instant.

### Flags

| Flag | Effect |
|---|---|
| `.\dev.ps1 -ApiOnly` | Backend only (no frontend) |
| `.\dev.ps1 -StopContainers` | Also stop the `api`/`postgres` containers on exit |

### If Windows blocks the script

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\dev.ps1
```

(Scope applies only to the current window.)

## First-time setup

### 1. Requirements

- **Docker Desktop** (Postgres/pgvector + API + web run in containers).
- **Node.js 20+** (frontend dev server; `npm` is used for `web/`).
- **Ollama installed natively on the host** — not in a container. Docker's WSL2 VM is too small for the model, and your GPU matters.

### 2. Pull the models

```powershell
ollama pull gemma4:e4b-it-qat  # the brain (~6.1 GB, QAT — stays resident in 16 GB RAM)
ollama pull nomic-embed-text  # embeddings (~274 MB)
```

### 3. Copy the environment file

```powershell
Copy-Item .env.example .env
```

Defaults are fine for local use; see [configuration.md](configuration.md).

### 4. Install frontend deps (first time only)

```powershell
npm --prefix web install
```

### 5. Run it

```powershell
.\dev.ps1
```

- Web app: **http://localhost:5173**
- API: **http://localhost:8000** (docs at `/docs`)
- Postgres: localhost:5432

## Alternative: everything in Docker (no Vite)

If you don't want the dev server, the compose file also builds and serves the
frontend as static files:

```powershell
docker compose up --build
```

- Web app: **http://localhost:8080**
- API: **http://localhost:8000**

## Making Mira aware of your machine (optional)

Her background mind loop runs in the API container. To feed her live signals
about your machine, run the host sampler every few minutes:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\mira_sense.ps1
```

Or schedule it with Windows Task Scheduler:

```powershell
schtasks /Create /TN "Mira Sense" /TR "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File \"C:\Users\sanka\OneDrive\Desktop\coding and stuff\projects\mira\scripts\mira_sense.ps1\"" /SC MINUTE /MO 5 /F
```

See [perception.md](perception.md).

## Useful commands

| Task | Command |
|---|---|
| API logs | `docker compose logs -f api` |
| Run backend tests | `python -m pytest tests` (from `backend/`) |
| Apply migrations manually | `docker compose exec api alembic upgrade head` |
| Query her DB directly | `docker compose exec postgres psql -U mira -d mira` |
| Start / stop everything | `docker compose up -d` / `docker compose stop` |

## Gotchas

- The API reaches Ollama via `host.docker.internal:11434`, so Ollama must be
  running on the host. If the API is up but replies hang, check `ollama serve`.
- `gemma4` runs on CPU (`OLLAMA_NUM_GPU=0`) because its vision projector crashes
  llama.cpp on low-VRAM GPUs — a known workaround, not a permanent setting.
- Because the backend source is bind-mounted into the container, **any approved
  self-edit Mira makes lands directly in your real repo** and survives rebuilds.
