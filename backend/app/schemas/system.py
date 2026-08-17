from datetime import datetime

from pydantic import BaseModel


class ProcessSample(BaseModel):
    """One top process — name, CPU percent, resident memory in MB."""

    name: str
    cpu: float = 0.0
    mem_mb: float = 0.0


class SystemSnapshot(BaseModel):
    """A point-in-time read of the voice's machine, reported by the host
    telemetry script. Everything is optional because the script may not be able
    to read every metric (e.g. battery on a desktop)."""

    ts: datetime | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    battery_percent: float | None = None
    battery_charging: bool | None = None
    idle_seconds: int | None = None
    top_processes: list[ProcessSample] = []


class SystemSnapshotOut(SystemSnapshot):
    """The stored snapshot — always carries its recorded timestamp."""

    ts: datetime