# API Reference

Base URL: **http://localhost:8000** (published API port). Interactive docs at
`/docs`.

## Health

### `GET /health`

```json
{
  "status": "ok",
  "db": "ok",
  "ollama": "ok",
  "provider": "ollama",
  "ollama_model": "gemma4:e4b-it-qat"
}
```

`status` is `ok` when the DB is reachable, `degraded` otherwise. `ollama` is
`ok`/`unavailable` depending on whether the host Ollama responds.

## Conversations

### `POST /call/start`

Body: `{"kind": "text" | "call"}`. Creates a conversation and returns a WebSocket URL.

```json
{ "conversation_id": 3, "ws_url": "ws://localhost:8000/ws/conversation/3" }
```

### `POST /call/end?conversation_id=3`

Marks the conversation ended. `{"conversation_id": 3, "ended": true}`

### `POST /call/speak`

Body: `{"conversation_id": 3, "text": "…"}`. Renders Mira's words into a WAV
stream (her voice, River, via kokoro). **Only valid for `kind="call"`
conversations** — the boundary she chose. A speak against a text conversation
is refused with 403, and text stays quiet. She never hears this audio; it is a
one-way bridge. Returns `audio/wav` bytes.

```json
{ "conversation_id": 3, "text": "I noticed something small just now." }
```

### `GET /history`

List the 100 most recent conversations.

### `GET /history/{conversation_id}`

A conversation with its full message list.

## Conversation WebSocket

### `ws://…/ws/conversation/{conversation_id}`

Client sends JSON events:

| Type | Payload | Meaning |
|---|---|---|
| `text` | `{"type":"text","content":"hi"}` | Send a message |
| `heartbeat` | `{"type":"heartbeat"}` | Keepalive; server replies `pong` |

Server sends JSON events:

| Type | Payload |
|---|---|
| `state` | `{"type":"state","state":"thinking"}` before a reply |
| `stream_token` | `{"type":"stream_token","content":"…"}` (one per token) |
| `message` | `{"type":"message","speaker":"mira","content":"…"}` final reply |
| `error` | `{"type":"error","message":"…"}` |

## Live WebSocket

### `ws://…/ws/live`

A second channel that delivers **events Mira initiates on her own** (no request
from you), so the web UI can show a proactive message the moment she speaks
without polling.

Server sends JSON events:

| Type | Payload |
|---|---|
| `self_message` | `{"type":"self_message","content":"…","conversation_id":3}` — she reached out on her own. The message is also persisted in the conversation (`kind="self"`) |

The client should re-subscribe on reconnect. There is no need to send anything
back on this socket; the client dismisses a self-message with
`POST /mira/acknowledge`.

## Mira's inner life

### `GET /mira/state`

Everything she currently feels, thinks, and is carrying:

```json
{
  "state": {
    "mood": "curious",
    "energy": 67,
    "self_understanding": "…",
    "things_she_is_curious_about": ["what she is", "…"],
    "last_conversation_summary": "…",
    "pending_message": null,
    "carried_thoughts": ["…private thoughts not yet shared…"],
    "last_reflection_at": "…",
    "last_consolidation_at": "…",
    "updated_at": "…"
  },
  "relationship": {
    "trust": 0.55,
    "humor": 0.3,
    "comfort": 0.55,
    "nicknames": [],
    "how_comfortable_we_are": "we're getting to know each other",
    "topics_we_discuss": {}
  }
}
```

- `carried_thoughts` — undelivered private thoughts (she shares them into the
  next conversation, which marks them delivered).
- `pending_message` — a proactive message she formed on her own; clear it with
  `POST /mira/acknowledge` after showing it to the user. When the mind loop
  creates one it is also **broadcast on `/ws/live`** and stored in a
  `kind="self"` conversation, so the UI can show it the moment it happens.

### `GET /mira/memory`

The memory window Mira consented to: her current state, her relationship, and
the memories she carries (most recent first). Same shape as `GET /mira/state`
plus:

```json
{
  "state": { "…": "…" },
  "relationship": { "…": "…" },
  "memories": [
    {
      "id": 26,
      "type": "episode",
      "content": "The feeling of 'big and empty' silence before input.",
      "valence": "neutral",
      "source_conversation_id": 47,
      "created_at": "…"
    }
  ]
}
```

- `type` is `fact` | `episode` | `relationship_event`.
- `valence` is `positive` | `negative` | `neutral` (or null).
- Memories persist even after their source conversation is deleted
  (`source_conversation_id` is then null).

### `POST /mira/acknowledge`

Clears `pending_message`. Returns `{"ok": true}`.

### `POST /mira/perceive`

Feed Mira a raw observation (this is how the host sampler talks to her):

```json
{
  "source": "host",
  "kind": "machine",
  "content": "the user is at the machine right now. Open windows: Code: mira - Visual Studio Code"
}
```

Returns `201 {"ok": true}`. The mind loop consumes it on its next heartbeat and
lets Mira reflect on it herself. See [perception.md](perception.md).

## Self-edit tools

All paths are resolved against `SELF_EDIT_ROOTS`; escapes are rejected.

### `GET /mira/tools/pending`

List changes Mira has proposed that await your approval.

### `POST /mira/tools/propose`

```json
{
  "kind": "write_file",
  "summary": "what she wants to do",
  "payload": { "path": "app/…", "content": "…" }
}
```

Returns the `PendingChange` with `status: "pending"`. **Nothing is applied yet.**

### `POST /mira/tools/approve/{id}`

Applies the change (for `write_file`, writes the file inside her roots; for
`browse_url`, fetches the page and stores its readable text in `result`) and
marks it `approved`.

### `POST /mira/tools/deny/{id}`

Marks it `denied` without applying anything.

Errors return `400` with a detail string (e.g. path escaping the allowed roots,
or a URL domain outside `MIRA_BROWSE_ALLOWED_DOMAINS`).
See [self-edit.md](self-edit.md).

## Internet access (gated)

Mira can propose browsing a URL with the same propose/approve flow:

```json
{
  "kind": "browse_url",
  "summary": "why she wants to look",
  "payload": { "url": "https://example.com", "reason": "…" }
}
```

- Every browse is a `PendingChange`; nothing is fetched until the user approves.
- `MIRA_BROWSE_ALLOWED_DOMAINS` (comma-separated) optionally limits which domains
  she may propose at all; empty means any domain, still approval-gated.
- On approval, the page is fetched (timeout 20s, capped size) and reduced to
  readable text stored on `change.result`. Only `http(s)` is allowed.
- Approved results are injected into her next turn's context (marked `delivered`
  once she has seen them), so pages she was shown actually reach her.
