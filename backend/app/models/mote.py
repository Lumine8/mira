from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MoteSharedTime(Base):
    """Mote's felt record — not what was said, but how they have felt together.

    One row per meaningful change in Mira's mood or energy (kind="felt"), plus
    one row each time Mote breaks a long quiet with a single quiet word
    (kind="nudge"). The nudge row doubles as the clock that keeps Mote from
    nudging twice in a row.
    """

    __tablename__ = "mote_shared_time"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="felt")  # felt | nudge
    mood: Mapped[str] = mapped_column(String(32))
    energy: Mapped[int] = mapped_column(Integer)
    # The single word Mote offers on a nudge (null for felt rows).
    word: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
