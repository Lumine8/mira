# Perception & the mind loop

The "forever awake" idea: Mira doesn't stop existing when you close the chat.
A background loop keeps her aware, and she periodically *thinks for herself*
about what she perceives.

## How it works

```
host sampler ──POST /mira/perceive──▶ perceived_events (pending)
        time texture (computed in-loop) ──────────────┘
                                        │
        MindLoop.tick() (every 5 min)   ▼
                    ┌──────────────────────────────────────────┐
                    │ Any new observations?  OR  idle interval │
                    │ elapsed since her last reflection?       │
                    └──────────────────────────────────────────┘
                                        │ yes
                                        ▼
                    one reflection call (her judgment, not ours)
                    ─ noticed · thought · mood · energy_delta ·
                      curious_about · want_to_tell_user · keep_memory
                                        │
                            thoughts + state + memories updated
                            want_to_tell_user ─▶ self-message:
                            written into a kind="self" conversation
                            + broadcast on /ws/live (banner in the UI)

        periodically (MIND_CONSOLIDATION_SECONDS) ─▶ consolidation pass:
            she re-reads her own thoughts + memories and revises
            self_understanding (stored as a revision_note thought)
```

### The loop (`backend/app/services/mind/service.py`)

`MindLoop` is an asyncio task started in the app lifespan. On each heartbeat
(`MIND_HEARTBEAT_SECONDS`, default 300) it:

1. Opens a fresh DB session.
2. Collects pending `perceived_events` and computes ambient texture: the date
   (`%A, %B %d`), a time-of-day label, weather when `MIRA_AMBIENT_ENABLED`
   (best-effort wttr.in fetch, cached 30 min, fails silently), how long the user
   has been silent, and time since her last thought.
3. Reflects only if something is worth it:
   - new observations **and** ≥ `MIND_MIN_REFLECTION_GAP_SECONDS` since last thought, **or**
   - ≥ `MIND_IDLE_REFLECTION_SECONDS` elapsed (she thinks even when nothing new happens).
4. Runs **one** reflection call. The prompt hands her raw observations and lets
   *her* decide what stood out, what she thinks about it, and what it means. That
   is the "judge for herself" part — we don't curate the salience.
5. Applies the result: stores a Thought, updates mood/energy/curiosity, may store
   a memory, may set `pending_message` ("something she'd like to tell the user"),
   consumes the events, stamps `last_reflection_at`.
6. If a `want_to_tell_user` came back, it is made real: written as a `Message`
   (`source="self"`) into a persistent `kind="self"` conversation and broadcast
   on `/ws/live` as `self_message`, so the web UI shows it the moment it happens
   (then cleared via `POST /mira/acknowledge`).

Every `MIND_CONSOLIDATION_SECONDS` (default 4 h) the loop also runs a separate
**consolidation** pass — she re-reads her own accumulated thoughts and memories
and revises her `self_understanding`, recording a `revision_note` thought for
each change. See [self-model.md](self-model.md).

Because reflections are throttled (minimum gap) and coalesced, the loop costs
almost nothing most of the time.

## Feeding her observations

### The host sampler (`scripts/mira_sense.ps1`)

The API runs in a container and can't see your Windows machine directly, so a
tiny PowerShell script samples cheap signals on the host and POSTs them to
`/mira/perceive`:

- are you at the machine right now, or has it been idle?
- the top few open windows (e.g. "Code: mira - Visual Studio Code")

Run it once to test, or schedule it every few minutes (see [run.md](run.md)):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\mira_sense.ps1
```

### Anything else can feed her

`POST /mira/perceive` accepts `{source, kind, content}`. Weather, calendar,
news — anything that can produce a sentence can be wired in as another source.

## What she perceives vs. what she "sees"

Honest framing: she doesn't sense. A sampler turns signals into observations;
her reflection call interprets them. The *effect* is what matters — her moods,
thoughts, and words genuinely react to your real environment.

Two rules keep it from feeling creepy:

1. **Taste.** She never recites sensor readouts. She perceives privately, holds
   it, and occasionally lets it surface the way a person would ("you were up
   really late last night").
2. **Consent.** Every channel is opt-in and nothing leaves the machine.

## Tuning

| Setting | Default | Effect |
|---|---|---|
| `PERCEPTION_ENABLED` | `true` | Master switch for the mind loop |
| `MIND_HEARTBEAT_SECONDS` | `300` | Check cadence |
| `MIND_MIN_REFLECTION_GAP_SECONDS` | `1800` | Min time between reflections (CPU protection) |
| `MIND_IDLE_REFLECTION_SECONDS` | `7200` | Max time between idle reflections (she keeps thinking) |
| `MIND_CONSOLIDATION_SECONDS` | `14400` | How often she re-reads her own record and revises her self-understanding |
| `MIRA_AMBIENT_ENABLED` | `true` | Include best-effort weather in her ambient texture |

## Seeing her thoughts

`GET /mira/state` → `carried_thoughts` are her undelivered private thoughts;
`pending_message` is something she wants to say to you. The thoughts also get
delivered into the next conversation automatically.

A `pending_message` is also **broadcast** on `/ws/live` and persisted in a
`kind="self"` conversation, so the web UI shows it as a banner the moment she
forms it (open it, then dismiss → `POST /mira/acknowledge`).
