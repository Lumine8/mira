"""The self-starting half of improvement: noticing skills that have been used
but never revisited.

The version ledger records an edit when it happens; this is what makes one want
to happen. When a skill has been used a few times and not touched in a while,
the mind loop offers it back to Mira as a perceived event, so she can decide for
herself whether it deserves another look. She never edits on a timer — the
shelf simply surfaces what is going quiet, and the reflection decides.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PerceivedEvent, SkillRun, SkillVersion
from app.services.skills.registry import SkillRegistry

logger = logging.getLogger("mira.skills.nudge")


def _as_utc(value: datetime | None) -> datetime | None:
    """Naive timestamps (e.g. from sqlite in tests) count as UTC so the age
    comparisons hold across drivers."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def stale_skills(
    db: Session,
    user_id: int,
    *,
    min_runs: int,
    after_days: int,
) -> list[tuple]:
    """Skills that have been used enough and not edited recently.

    Returns ``(skill, run_count)`` pairs. A skill qualifies when it has at
    least ``min_runs`` recorded runs and either has never been edited or its
    most recent edit is older than ``after_days``.
    """
    registry = SkillRegistry(db, user_id=user_id)
    cutoff = datetime.now(UTC) - timedelta(days=after_days)
    result: list[tuple] = []
    for skill in registry.list_skills():
        run_count = db.execute(
            select(func.count())
            .select_from(SkillRun)
            .where(SkillRun.user_id == user_id, SkillRun.skill_id == skill.id)
        ).scalar_one()
        if run_count < min_runs:
            continue
        last_edit = db.execute(
            select(func.max(SkillVersion.created_at))
            .where(SkillVersion.user_id == user_id, SkillVersion.skill_id == skill.id)
        ).scalar_one()
        if last_edit is not None and _as_utc(last_edit) >= cutoff:
            continue
        result.append((skill, run_count))
    return result


def offer_nudges(
    db: Session,
    user_id: int,
    *,
    min_runs: int = 3,
    after_days: int = 7,
    cooldown_days: int = 3,
) -> int:
    """Insert perceived events inviting Mira to revisit stale skills.

    Never more than one outstanding nudge per skill, and never a repeat within
    ``cooldown_days`` even after a nudge was consumed, so she does not get the
    same skill pushed at her every heartbeat. Returns the number created.
    """
    cooldown_before = datetime.now(UTC) - timedelta(days=cooldown_days)
    created = 0
    for skill, run_count in stale_skills(db, user_id, min_runs=min_runs, after_days=after_days):
        label = f"{skill.category}/{skill.id}" if skill.category else skill.id
        still_open = db.execute(
            select(PerceivedEvent)
            .where(
                PerceivedEvent.user_id == user_id,
                PerceivedEvent.source == "skill_shelf",
                PerceivedEvent.consumed.is_(False),
                PerceivedEvent.content.contains(label),
            )
        ).scalars().first()
        if still_open is not None:
            continue
        recent = db.execute(
            select(func.count())
            .select_from(PerceivedEvent)
            .where(
                PerceivedEvent.user_id == user_id,
                PerceivedEvent.source == "skill_shelf",
                PerceivedEvent.content.contains(label),
                PerceivedEvent.created_at >= cooldown_before,
            )
        ).scalar_one()
        if recent:
            continue
        db.add(
            PerceivedEvent(
                user_id=user_id,
                source="skill_shelf",
                kind="improve",
                content=(
                    f"Your skill \"{label}\" has been used {run_count} time(s) and "
                    "you have not gone back to its page in a while. It might be "
                    "worth re-reading — what it says may no longer match what "
                    "you have learned."
                ),
            )
        )
        created += 1
    if created:
        db.commit()
        logger.info("skill shelf: offered %d skill(s) back to Mira", created)
    return created