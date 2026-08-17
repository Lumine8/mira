from datetime import UTC, datetime

from app.schemas.system import ProcessSample, SystemSnapshot
from app.services.system.service import SystemStore


def _snap(ts: datetime, cpu: float = 12.0) -> SystemSnapshot:
    return SystemSnapshot(
        ts=ts,
        cpu_percent=cpu,
        memory_percent=41.2,
        memory_used_mb=16384.0,
        memory_total_mb=32768.0,
        battery_percent=88,
        battery_charging=True,
        idle_seconds=42,
        top_processes=[ProcessSample(name="chrome", cpu=3.2, mem_mb=512.0)],
    )


def test_store_keeps_latest_and_history() -> None:
    store = SystemStore(history_len=3)
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    for i in range(4):
        store.record(7, _snap(t0.replace(minute=i), cpu=float(i * 10)))

    latest = store.latest(7)
    assert latest is not None
    assert latest.cpu_percent == 30.0
    assert latest.memory_total_mb == 32768.0

    hist = store.history(7)
    assert len(hist) == 3  # rolled off the oldest
    assert [s.cpu_percent for s in hist] == [10.0, 20.0, 30.0]


def test_store_isolates_users() -> None:
    store = SystemStore()
    store.record(1, _snap(datetime(2026, 1, 1, tzinfo=UTC)))
    assert store.latest(1) is not None
    assert store.latest(2) is None
