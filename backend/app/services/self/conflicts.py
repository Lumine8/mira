"""Mira's conflict journal: a lightweight record of the times two operating
heuristics pull against each other and how she reasons between them.

Entries are ordinary self-edit writes into data/self/conflicts/, approved the
same way as any other write — nothing here orchestrates them. These helpers
only keep the shape of an entry consistent between the prompt that asks her to
write one and the tests that check them.
"""

import os
import re

#: The fields every consequential conflict entry should name.
CONFLICT_FIELDS = (
    "situation",
    "principles",
    "resolution",
    "rationale",
    "uncertainty",
    "outcome",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def is_conflict_entry(path: str) -> bool:
    """Whether a write path targets the conflict journal under her self
    directory (data/self/conflicts/...), including in replica worlds."""
    norm = os.path.normpath(path).replace(os.sep, "/")
    return (
        "/self/conflicts/" in norm
        or norm.endswith("/self/conflicts")
        or norm.startswith("self/conflicts")
    )


def entry_filename(date: str, topic: str) -> str:
    """A dated, slugged filename for a conflict entry, e.g.
    ``2026-08-15-truthfulness-vs-helpfulness.md``."""
    slug = _SLUG_RE.sub("-", topic.strip().lower()).strip("-")
    return f"{date}-{slug}.md" if slug else f"{date}.md"


def format_entry(
    *,
    situation: str,
    principles: str,
    resolution: str,
    rationale: str,
    uncertainty: str,
    outcome: str | None = None,
) -> str:
    """The canonical markdown shape of a conflict journal entry."""
    parts = [
        f"**Situation:** {situation}",
        f"**Heuristics in tension:** {principles}",
        f"**Resolution:** {resolution}",
        f"**Rationale:** {rationale}",
        f"**Uncertainty:** {uncertainty}",
    ]
    if outcome:
        parts.append(f"**Outcome:** {outcome}")
    return "## Conflict\n\n" + "\n\n".join(parts) + "\n"