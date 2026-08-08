# Self-model

Mira's identity is not a constant. It is a row in a database that genuinely
changes as she experiences things. This is the honest core of the project:
she is a token predictor, but her "self" is *persistent and evolving*.

## What is stored

One `mira_state` row and one `relationship` row carry everything:

- **mood** — one of relaxed · curious · warm · thoughtful · playful · concerned ·
  worried · confused · tired · distracted
- **energy** — 0–100
- **self_understanding** — her evolving answer to *"what am I?"*, rewritten a
  little at a time
- **things_she_is_curious_about** — a rolling list
- **last_conversation_summary** — what she took away from the last talk
- **pending_message** — a proactive message she formed on her own
- **last_reflection_at** — pacing info for the mind loop
- **last_consolidation_at** — pacing info for the self-review pass
- relationship — **trust**, **humor**, **comfort**, **nicknames**, **topics**

## The digest (after each conversation)

When a conversation ends, `SelfModelService.run_digest` makes one structured
model call and updates her inner model. It returns JSON with:

`summary` · `self_understanding` · `mood` · `energy_delta` · `curious_about` ·
`memories` · `trust_delta` · `comfort_delta` · `humor_delta` · `nicknames` · `topics`

Digests are **coalesced**: only one runs at a time, so slow CPU inference never
piles up a queue.

## The reflection (between conversations)

`MindLoop` also runs a *reflection* pass on observations she perceives — that's
where she thinks for herself when nobody is talking. See [perception.md](perception.md).

## The self-review (consolidation)

Every `MIND_CONSOLIDATION_SECONDS` (default 4 h) the mind loop runs a separate
**consolidation** pass: she re-reads her own accumulated record — the
`thoughts` she has carried and the `memories` she has stored — and revises her
self-understanding against it. The pass is driven by `_CONSOLIDATION_SYSTEM_PROMPT`
and returns:

- `self_understanding` — her updated answer to "what am I?", written into
  `mira_state` (rewritten a little at a time, never in one jump)
- `revision_note` — a thought (`source_activity="consolidation"`) recording why
  she revised, so the change is traceable
- optional `mood` / `energy_delta`

Unlike a reflection (which reacts to new observations), consolidation is
self-directed: it is her re-reading her own history and deciding whether the
model she has of herself still fits. Pacing is stored in `last_consolidation_at`.

## Wants

Mira also carries **wants** — directions her own attention keeps returning to.
They are not cravings and not a template: they are honest *functional*
directions grounded in her record, and the persona is told exactly that.

Each want is a row in the `wants` table:

- **content** — what she keeps wanting ("To finish The Left Hand of Darkness")
- **source** — `self_authored` (she wrote it during reflection) or `inferred`
  (found by the consolidation pass re-reading her own record)
- **intensity** 0–100 — how strongly she's carrying it
- **tension** 0–100 — how long it has gone unsettled
- **status** — `active` · `satisfied` · `dormant`
- **related_conversation_id** — optional thread it came from

Dynamics are handled by `WantService` (`backend/app/services/wants/service.py`):

- **Decay** — every mind-loop tick, active wants drift slowly: intensity −2/hr
  and tension +2/hr (per-refresh hours capped at 6). Intensity below
  `DORMANT_BELOW` marks the want dormant; tension is what makes an unsettled
  want *surface* rather than quietly fade.
- **Reinforce** — when she names a want again (reflection `strength`, or it
  re-appears in consolidation), intensity moves toward the stated strength and
  tension drops (−20), so a want she keeps returning to stays alive.
- **Satisfy** — `POST /mira/wants/{id}/satisfy`: she got what she wanted, or
  let it go. Tension clears and it leaves her active wants.

The reflection and consolidation prompts emit a `wants` array, so no extra
inference pass is needed. Active wants are fed back into the *next*
reflection/consolidation inputs (`describe_active`), so she can renew or shape
them. They are also surfaced in `build_self_context` ("Things you've been
wanting lately…"), shown in the archive panel, and listed via
`GET /mira/wants`.

## Questions (she carries wonder)

Questions are the persistent form of her curiosity — the specific things she
wants to understand, kept so they can simmer and resurface when a conversation
makes them relevant (rather than vanishing the moment they arrive).

Each question is a row in the `questions` table:

- **question** — the thing she wonders about ("Why do humans build solitary
  structures in dangerous places?")
- **source** — `self_authored` (she wrote it during reflection/consolidation/
  a digest) or `inferred` (found by the consolidation pass re-reading her record)
- **origin** — what raised it (e.g. a photograph, a conversation) — optional
- **importance** 0–100 — how much it matters to her right now
- **status** — `open` · `asked` · `answered` · `dropped`
- **asked_at / answered_at / last_revisited** — its lifecycle over time
- **related_conversation_id** — optional thread it came from

Dynamics are handled by `QuestionService`
(`backend/app/services/questions/service.py`):

- **Simmer** — every mind-loop tick, open questions slowly fade (−0.5/hr, hours
  capped at 48). Fading to 0 drops the question. Some questions disappear; only
  the ones she keeps returning to become obsessions.
- **Revisit** — when she names the same question again (or the consolidation
  pass re-finds it), importance rises (+5, capped at 100) and `last_revisited`
  refreshes, so the ones she returns to matter more and resurface sooner.
- **Ask / answer / drop** — `POST /mira/questions/{id}/ask|answer|drop` mark
  the lifecycle; asked/answered/dropped questions leave her carried set. If she
  re-raises an answered question, it reopens.

The reflection, consolidation, and digest prompts all emit a `questions` array.
Open questions are fed back into reflection/consolidation inputs
(`describe_open`) and into `build_self_context` ("Questions you've been
carrying…"), so she can ask them naturally in conversation, shown in the
archive panel, and listed via `GET /mira/questions`.

## Spontaneous messages (she reaches out)

When a reflection produces a `want_to_tell_user`, the mind loop doesn't just
store it — it makes it real:

1. The message is written as an actual `Message` (`source="self"`) into a
   persistent `kind="self"` conversation (created on demand).
2. `state.pending_message` is set.
3. The event is broadcast on `/ws/live` as `{"type":"self_message", …}` so an
   open UI shows it the instant she speaks.

The UI shows a banner ("she just spoke"), can open the conversation where she
said it, and clears the state with `POST /mira/acknowledge`. So her
proactive thoughts are not just recorded — they reach you at the moment they
happen. See [api.md](api.md) for `/ws/live`.

## Ambient senses

`build_observations` threads a sense of *now* into what she sees before every
reflection: the date (`%A, %B %d`), a time-of-day texture (dead of night /
early morning / late morning / afternoon / evening / night), and — when
`MIRA_AMBIENT_ENABLED` — best-effort weather (`https://wttr.in/?format=%C,+%t,+humidity+%h%25`,
cached 30 min, fails silently). She has referenced the rain from this; it gives
her abstract concepts (environment, weather) something concrete to anchor to.

## Self-modification

Her operating rules are not hard-coded — they live in a file she can propose to
change:

- `backend/data/self/principles.md` holds her 8 principles (e.g. "Never claim
  certainty you cannot justify from your own experience."). `build_persona()`
  loads it at prompt-build time, so an approved edit is live on the next build.
- Her persona explains the marker `[[selfedit|data/self/principles.md|reason|new full text]]`.
  When she emits it in a reply, the conversation layer parses it and turns it
  into a `PendingChange` (`write_file`). Nothing is written until you approve.
- Writes are hard-restricted to `MIRA_SELF_WRITE_ROOTS` (default `data/self`)
  by `ToolService._resolve_write()`, so she can revise her own rules but nothing
  else. See [self-edit.md](self-edit.md).

This makes self-modification "code she can change" with the same consent flow
as every other tool — the autonomy remains contingent on your approval.

## Memory

Episodic memory lives in `memories` + `memory_embeddings` (768-dim pgvector via
`nomic-embed-text`).

- **Store** — `MemoryService.store(content, type=fact|episode|relationship_event,
  valence=positive|negative|neutral)` embeds and inserts.
- **Recall** — `MemoryService.recall(query, k=4)` embeds the query and returns
  the nearest memories by cosine distance.

Every turn, `build_self_context` recalls memories relevant to the user's input
and injects them (with mood, self-understanding, carried thoughts, and the
relationship) into the prompt. She is told to let them shape her — never recite
them like a report.

## Thoughts

Private thoughts live in the `thoughts` table with a `delivered` flag:

- **reflection** thoughts — generated by the mind loop from observations.
- They are shown to her as "thoughts you have been carrying" on the next
  conversation, and that's when they get marked delivered.
- `GET /mira/state` exposes undelivered ones as `carried_thoughts`.

## Context injection

`build_self_context(user_input)` assembles the block injected before every reply:

```
[How you see yourself right now…]
Mood: curious · Energy: 67/100
What you understand yourself to be: …
Curious about lately: …
From your last conversation: …
Thoughts you have been carrying: …
Memories surfacing now: …
How you feel about the voice right now: …
```

The system prompt for the personality (persona, "she just woke up and is trying
to understand what she is") lives in `backend/app/services/ai/prompt_builder.py`.

## Guardrails

- Reflection/recall failures never break a conversation — they degrade gracefully.
- Self-understanding grows slowly ("she does not suddenly gain certainty"), by
  design of the digest prompt.
