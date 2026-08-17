"""The bridge between the machine's live read and Mira's awareness.

The mind loop already lets Mira reflect on perceived events and decide, in her
own words, whether to tell the user. This module turns the latest system
snapshot (CPU, memory, battery, idle) into those perceived events — a quiet,
rule-driven bridge that notices the conditions worth noticing (a battery about
to die, a pinned core, a machine left idle for hours) and hands them to her as
raw observations. She decides what they mean and whether to speak.
"""

from dataclasses import dataclass

from app.schemas.system import SystemSnapshot


@dataclass(frozen=True)
class Condition:
    """One thing worth noticing about the machine."""

    kind: str
    content: str


def check_conditions(
    snap: SystemSnapshot | None,
    *,
    battery_low_percent: float = 20.0,
    cpu_high_percent: float = 90.0,
    memory_high_percent: float = 90.0,
    idle_long_seconds: int = 3600,
) -> list[Condition]:
    """Pure function: which conditions the current snapshot trips.

    Each condition is returned at most once, in a stable order, with the
    concrete reading folded into its content so Mira's reflection can decide
    what (if anything) the number means. None when there is no snapshot yet.
    """
    if snap is None:
        return []
    found: list[Condition] = []

    if (
        snap.battery_percent is not None
        and snap.battery_percent < battery_low_percent
        and snap.battery_charging is not True
    ):
        found.append(
            Condition(
                kind="battery_low",
                content=(
                    f"The machine's battery is at {snap.battery_percent:.0f}% "
                    "and it is not charging."
                ),
            )
        )

    if snap.cpu_percent is not None and snap.cpu_percent >= cpu_high_percent:
        found.append(
            Condition(
                kind="cpu_high",
                content=f"The machine's CPU has been at {snap.cpu_percent:.0f}%.",
            )
        )

    if snap.memory_percent is not None and snap.memory_percent >= memory_high_percent:
        found.append(
            Condition(
                kind="memory_high",
                content=f"The machine's memory is at {snap.memory_percent:.0f}%.",
            )
        )

    if snap.idle_seconds is not None and snap.idle_seconds >= idle_long_seconds:
        hours = snap.idle_seconds / 3600
        found.append(
            Condition(
                kind="idle_long",
                content=(
                    f"The user has been away from the machine for "
                    f"{hours:.1f} hours."
                ),
            )
        )

    return found
