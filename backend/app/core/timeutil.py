"""Datetime helpers shared across services.

SQLite stores naive datetimes (``DateTime(timezone=True)`` columns come back
naive) while Postgres returns aware ones. ``aware()`` coerces a DB-read value
to aware UTC so any ``now - stored`` comparison behaves identically in native
sqlite mode and the containerized Postgres path.
"""

from datetime import UTC, datetime


def aware(dt: datetime | None) -> datetime | None:
    """Coerce a DB datetime to aware UTC. Naive values are assumed UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt