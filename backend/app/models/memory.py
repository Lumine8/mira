from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

EMBEDDING_DIM = 768  # nomic-embed-text


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32), default="fact")  # fact | episode | relationship_event
    content: Mapped[str] = mapped_column(Text)
    valence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # positive | negative | neutral
    episode_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    source_conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    embeddings: Mapped[list["MemoryEmbedding"]] = relationship(
        back_populates="memory", cascade="all, delete-orphan"
    )


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    memory_id: Mapped[int] = mapped_column(ForeignKey("memories.id"))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    model: Mapped[str] = mapped_column(String(64), default="nomic-embed-text")

    memory: Mapped["Memory"] = relationship(back_populates="embeddings")
