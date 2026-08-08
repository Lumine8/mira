from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EMBEDDING_DIM, Memory, MemoryEmbedding
from app.services.ai.base import AIProvider


class MemoryService:
    """Episodic memory over pgvector: store embedded memories, recall by similarity."""

    def __init__(self, db: Session, provider: AIProvider) -> None:
        self.db = db
        self.provider = provider

    async def recall(self, query: str, *, k: int = 5) -> list[dict]:
        """Return the ``k`` memories most relevant to ``query``."""
        vec = await self.provider.embed(query)
        rows = self.db.execute(
            select(Memory)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .order_by(MemoryEmbedding.embedding.cosine_distance(vec))
            .limit(k)
        ).scalars()
        return [
            {
                "content": m.content,
                "type": m.type,
                "valence": m.valence,
            }
            for m in rows
        ]

    async def store(
        self,
        content: str,
        *,
        type_: str = "fact",
        valence: str | None = None,
        conversation_id: int | None = None,
        metadata: dict | None = None,
    ) -> Memory:
        mem = Memory(
            type=type_,
            content=content,
            valence=valence,
            episode_metadata=metadata,
            source_conversation_id=conversation_id,
        )
        self.db.add(mem)
        self.db.flush()
        vec = await self.provider.embed(content)
        self.db.add(
            MemoryEmbedding(memory_id=mem.id, embedding=vec, model=self._embed_label())
        )
        self.db.commit()
        self.db.refresh(mem)
        return mem

    def _embed_label(self) -> str:
        try:
            if self.provider.name == "gemini":
                return get_settings().gemini_embed_model
        except Exception:  # pragma: no cover
            pass
        return getattr(self.provider, "embed_model", None) or "nomic-embed-text"
