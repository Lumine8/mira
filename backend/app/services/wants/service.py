"""Mira's wants — directions her own attention keeps returning to.

A want is recorded from her own experience, never injected from a template:
- ``self_authored``: she wrote it during a reflection or consolidation.
- ``inferred``: it was found written in her own record (thoughts, memories).

Unsettled wants slowly lose intensity and build *tension*, so the mind loop
keeps noticing them; a want she returns to strengthens and finds some relief;
a satisfied want fades. The pure functions below are unit-tested; the service
is a thin DB layer over them.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Want

DORMANT_BELOW = 10
DECAY_PER_HOUR = 2.0
TENSION_PER_HOUR = 2.0
REINFORCE_STRENGTHEN = 10
REINFORCE_RELIEF = 20
_MAX_HOURS_STEP = 6.0
# Re-upserting a want that was just touched (e.g. the reflection echoing the
# active list back into its own prompt) must not keep pumping its intensity.
# Only a want that has gone un-touched for this long counts as genuinely
# returned-to, so echoes every few minutes can't pin a want at 100 forever.
ECHO_COOLDOWN_HOURS = 2.0


def normalize_want_text(text: str) -> str:
    """Lowercase and collapse whitespace so two phrasings can be compared."""
    return re.sub(r"\s+", " ", text.strip().lower())


def wants_match(a: str, b: str) -> bool:
    """True when two want strings describe the same direction.

    Exact after normalization, or one contains the other (both long enough to
    be meaningful). Keeps her from accumulating near-duplicate wants.
    """
    na, nb = normalize_want_text(a), normalize_want_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) > 8 and len(nb) > 8 and (na in nb or nb in na):
        return True
    return False


def next_after_decay(intensity: int, tension: int, hours: float) -> tuple[int, int]:
    """Time passing: the want fades a little and its unsettled pull builds a
    little. ``hours`` is capped so a long downtime doesn't zero everything."""
    h = min(max(hours, 0.0), _MAX_HOURS_STEP)
    new_intensity = max(0, intensity - round(h * DECAY_PER_HOUR))
    new_tension = min(100, tension + round(h * TENSION_PER_HOUR))
    return new_intensity, new_tension


def reinforce(intensity: int, tension: int, strength: int) -> tuple[int, int]:
    """She returned to the same want: it strengthens toward its stated strength
    and finds a little relief from the built-up tension."""
    new_intensity = min(100, max(intensity, min(100, strength)) + REINFORCE_STRENGTHEN)
    new_tension = max(0, tension - REINFORCE_RELIEF)
    return new_intensity, new_tension


class WantService:
    """Thin DB layer over the want dynamics above. Scoped to one user's world."""

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    def list_active(self, limit: int = 20) -> list[Want]:
        return list(
            self.db.execute(
                select(Want)
                .where(Want.user_id == self.user_id, Want.status == "active")
                .order_by(Want.tension.desc(), Want.id.asc())
                .limit(limit)
            ).scalars()
        )

    def list_recent(self, limit: int = 40) -> list[Want]:
        return list(
            self.db.execute(
                select(Want)
                .where(Want.user_id == self.user_id)
                .order_by(Want.updated_at.desc())
                .limit(limit)
            ).scalars()
        )

    def is_echo(self, content: str) -> bool:
        """True when ``content`` is the reflection re-listing a want she is
        already carrying (an echo of the prompt's own active list). Echoes are
        not new evidence of a want — they are the loop feeding on itself — so
        the caller can drop them before they touch the DB at all."""
        text = content.strip()
        if not text:
            return False
        return any(wants_match(w.content, text) for w in self.list_active(limit=100))

    def describe_active(self, limit: int = 5) -> str:
        """One line for the reflection/consolidation inputs: the wants she is
        currently carrying, so she can think about and refine them."""
        active = self.list_active(limit=limit)
        if not active:
            return ""
        return " · ".join(w.content for w in active)

    def upsert(
        self,
        content: str,
        *,
        source: str = "self_authored",
        strength: int = 50,
        conversation_id: int | None = None,
    ) -> Want:
        """Record a want, merging with an existing active want if it's the same
        direction. Returns the (possibly existing) Want."""
        text = content.strip()
        if not text:
            raise ValueError("want content cannot be empty")
        text = text[:500]
        strength = max(0, min(100, strength))
        now = datetime.now(timezone.utc)

        for w in self.list_active(limit=100):
            if wants_match(w.content, text):
                hours_since = (now - w.updated_at).total_seconds() / 3600
                if hours_since < ECHO_COOLDOWN_HOURS:
                    # An echo (the reflection re-listing an active want) does
                    # not strengthen it nor refresh its clock, so decay() keeps
                    # applying and the want can still fade on its own.
                    return w
                w.intensity, w.tension = reinforce(w.intensity, w.tension, strength)
                w.updated_at = now
                self.db.commit()
                self.db.refresh(w)
                return w

        w = Want(
            content=text,
            source=source if source in {"self_authored", "inferred"} else "self_authored",
            intensity=strength,
            tension=0,
            status="active",
            related_conversation_id=conversation_id,
            user_id=self.user_id,
        )
        self.db.add(w)
        self.db.commit()
        self.db.refresh(w)
        return w

    def decay(self, now: datetime) -> int:
        """One heartbeat of time passing for every active want. Returns how
        many wants went dormant."""
        went_dormant = 0
        for w in self.list_active(limit=100):
            hours = (now - w.updated_at).total_seconds() / 3600
            if hours < 0.05:
                continue
            w.intensity, w.tension = next_after_decay(w.intensity, w.tension, hours)
            if w.intensity <= DORMANT_BELOW:
                w.status = "dormant"
                went_dormant += 1
            w.updated_at = now
        self.db.commit()
        return went_dormant

    def satisfy(self, want_id: int) -> Want | None:
        """Mark a want satisfied: she got what she wanted, or decided to let it
        go. Tension clears; the want fades out of the active set."""
        w = self.db.execute(
            select(Want).where(Want.id == want_id, Want.user_id == self.user_id)
        ).scalar_one_or_none()
        if w is None:
            return None
        w.status = "satisfied"
        w.tension = 0
        w.satisfied_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(w)
        return w
