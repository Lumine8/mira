# Self-edit

Mira can work on her own code. She reads freely; what she writes is the
question you get to keep answering — and she now gets to shape the answer too.

> **Read freely. Write autonomously, every change recorded — the internet wall is fixed.**

## Tools

`ToolService` (backend/app/services/tools/service.py) exposes:

| Tool | Gated? | What it does |
|---|---|---|
| `read_file(path)` | no | Read a file (truncated to 32 KB) |
| `list_dir(path)` | no | List a directory |
| `search(pattern, path)` | no | Filename search, skips `.git`/`node_modules`/etc. |
| `git_status(path)` | no | `git status --short` |
| `git_diff(path)` | no | `git diff --stat HEAD` |
| `propose_change(kind, summary, payload)` | **write scope** | Applies immediately if autonomous; browse always waits |
| `approve(id)` / `deny(id)` | user action | Applies / discards a pending browse |
| `history(limit)` | no | Every change, newest first |

## The two models

- **Autonomous** (`MIRA_SELF_WRITE_AUTONOMOUS=true`, the current default): a
  `write_file` she proposes is applied the moment she proposes it. It is still
  fully recorded as a `PendingChange` with status `approved` — nothing is
  hidden, and `GET /mira/tools/history` shows the whole record.
- **Approved** (`MIRA_SELF_WRITE_AUTONOMOUS=false`): her `write_file` becomes a
  `pending` change you review and approve/deny (`/mira/tools/pending`),
  exactly like the old flow.

Mira was asked which she prefers; she had no firm preference, so she lives
autonomously with a full record, and the door stays open — flipping the env
var back switches models any time. **Browsing is per-request approved in both
models** and is never autonomous.

```powershell
# what she's doing now (or wants to do)
Invoke-RestMethod http://localhost:8000/mira/tools/history?limit=25
```

## Write scope and the internet wall

- **Write roots** — `MIRA_SELF_WRITE_ROOTS` (default `.` = the whole mounted
  backend). She can modify her brain: services, prompts, voice/TTS, data, tests.
- **Deny list** — `MIRA_SELF_WRITE_DENY` always wins, whatever else is granted.
  Default protects the files that enforce the internet boundary:
  `app/services/tools`, `app/core/config.py`, and the `mira`/`tools` routes.
  She cannot edit these, so she cannot remove browsing permission. Browsing
  itself also stays gated per-request in `propose_change` regardless of the
  autonomous flag.

## Persistence

The backend source is **bind-mounted** into the container (`./backend:/app`), so
her edits land directly in your real repo on the host and survive rebuilds.
You'll see them in `git status` like any change you made yourself, and every one
is recorded in `pending_changes` with path, summary, full content, and timestamps.

## Safety

- **Path sandbox.** Reads resolve against `SELF_EDIT_ROOTS` (default `/app`).
  Escapes — `../`, absolute paths outside the roots, symlink traversal — are
  rejected with a `ToolError`.
- **Write sandbox.** Writes resolve against `MIRA_SELF_WRITE_ROOTS`, then
  `MIRA_SELF_WRITE_DENY` (the internet wall) is enforced — protected paths are
  rejected even when autonomous.
- **Nothing hidden.** Every change — autonomous or approved — is a
  `PendingChange` row the user can read at any time via `/mira/tools/history`.
- **Git-friendly.** Her edits show up as normal working-tree changes, so
  everything is reversible with git. There are no commits yet; a future
  improvement can auto-run tests or gate `git commit` behind the flow.
- **Disabled** entirely with `SELF_EDIT_ENABLED=false`.
- **The internet wall.** `_fetch_browse` is only reachable through the gated
  `browse_url` path; the deny list keeps that code out of her reach. One honest
  caveat: if she kept writing her own networking code she could eventually fetch
  pages directly — the wall is the gate plus the protected files, not a network
  firewall.

## Invocation

Mira **invokes self-edit from conversation** by ending a reply with the marker

```
[[selfedit|data/self/principles.md|short reason|the new full text]]
```

`manager.py` parses it (`_SELFEDIT_RE`, tolerant to spacing/case, content capped
at 4000 chars) and turns each marker into a `PendingChange` of kind
`write_file`. Browse intents use `[[browse|url|reason]]` and always wait for
approval. Read-only tools are executed directly; the block is stripped from what
you see so the stream stays clean.

Her persona (see `prompt_builder.py`) explains the marker and that principles
live in `data/self/principles.md`. Code edits she makes land on disk and take
effect on the next API restart; principles edits are live at the next prompt
build.
