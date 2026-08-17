from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

EMBEDDING_DIM = 768  # nomic-embed-text

# Postgres gets true JSONB; sqlite (tests) falls back to plain JSON so the
# whole model set can be created in-memory.
JSONB_PORTABLE = JSONB().with_variant(JSON(), "sqlite")

# Embeddings: pgvector's Vector column on Postgres, a plain JSON float list on
# sqlite (the no-Docker native setup). Similarity is computed in Python there.
VECTOR_PORTABLE = Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(32), default="fact")  # fact | episode | relationship_event
    content: Mapped[str] = mapped_column(Text)
    valence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # positive | negative | neutral
    episode_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB_PORTABLE, nullable=True)
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
    embedding: Mapped[list[float]] = mapped_column(VECTOR_PORTABLE)
    model: Mapped[str] = mapped_column(String(64), default="nomic-embed-text")

    memory: Mapped["Memory"] = relationship(back_populates="embeddings")
