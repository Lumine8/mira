from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HostToast(Base):
    """A native toast the host should pop for the voice.

    Enqueued whenever Mira reaches out on her own — the mind loop's self
    messages and the reminders loop's fired held things. The desktop companion
    (Electron) shows its own alerts over the live hub; this table is the
    companion-free path: a small host script polls pending rows, pops a real
    Windows toast, and marks them delivered. Nothing is delivered until a
    client says so, so a toast that was never shown is retried next poll.
    """

    __tablename__ = "host_toasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # What kind of reach-out produced it: self (mind loop) or reminder.
    source: Mapped[str] = mapped_column(String(16), default="self")
    title: Mapped[str] = mapped_column(String(120), default="Mira")
    content: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
