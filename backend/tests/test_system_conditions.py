from datetime import UTC, datetime

from app.schemas.system import SystemSnapshot
from app.services.system.conditions import check_conditions


def _snap(**kw) -> SystemSnapshot:
    return SystemSnapshot(ts=datetime.now(UTC), **kw)


def test_no_snapshot_yields_nothing() -> None:
    assert check_conditions(None) == []


def test_battery_low_when_discharging() -> None:
    conds = check_conditions(_snap(battery_percent=14.0, battery_charging=False))
    kinds = [c.kind for c in conds]
    assert "battery_low" in kinds
    assert "14%" in next(c.content for c in conds if c.kind == "battery_low")


def test_battery_low_not_fired_while_charging() -> None:
    conds = check_conditions(_snap(battery_percent=14.0, battery_charging=True))
    assert "battery_low" not in [c.kind for c in conds]


def test_cpu_high_threshold() -> None:
    conds = check_conditions(_snap(cpu_percent=95.0))
    assert "cpu_high" in [c.kind for c in conds]
    conds = check_conditions(_snap(cpu_percent=50.0))
    assert "cpu_high" not in [c.kind for c in conds]


def test_memory_high_threshold() -> None:
    conds = check_conditions(_snap(memory_percent=92.0))
    assert "memory_high" in [c.kind for c in conds]
    conds = check_conditions(_snap(memory_percent=60.0))
    assert "memory_high" not in [c.kind for c in conds]


def test_idle_long() -> None:
    conds = check_conditions(_snap(idle_seconds=7200))
    assert "idle_long" in [c.kind for c in conds]
    assert "2.0 hours" in next(c.content for c in conds if c.kind == "idle_long")
    conds = check_conditions(_snap(idle_seconds=300))
    assert "idle_long" not in [c.kind for c in conds]


def test_thresholds_are_configurable() -> None:
    conds = check_conditions(
        _snap(battery_percent=25.0, cpu_percent=80.0),
        battery_low_percent=30.0,
        cpu_high_percent=70.0,
    )
    kinds = [c.kind for c in conds]
    assert "battery_low" in kinds
    assert "cpu_high" in kinds