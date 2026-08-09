import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EMBEDDING_DIM, Memory, MemoryEmbedding
from app.services.ai.base import AIProvider

# Live dedup: if a memory is this similar to one we already have (embedding
# cosine plus normalized text overlap), skip storing it. The reflection loop
# keeps re-deriving near-identical thoughts (e.g. the weather), and without
# this every one became a new memory.
_DEDUP_COSINE = 0.90
_DEDUP_TEXT = 0.60


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


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
        vec = await self.provider.embed(content)
        dup = await self._find_duplicate(content, vec)
        if dup is not None:
            return dup
        mem = Memory(
            type=type_,
            content=content,
            valence=valence,
            episode_metadata=metadata,
            source_conversation_id=conversation_id,
        )
        self.db.add(mem)
        self.db.flush()
        self.db.add(
            MemoryEmbedding(memory_id=mem.id, embedding=vec, model=self._embed_label())
        )
        self.db.commit()
        self.db.refresh(mem)
        return mem

    async def _find_duplicate(self, content: str, vec: list[float]) -> Memory | None:
        """Return an existing memory that is a near-duplicate of ``content``.

        Checks recent memories first (the loop re-derives the same thought within
        a short window); the window is a few days so older distinct memories are
        never mistaken for echoes. Both embeddings and text must be close.
        """
        from datetime import timedelta

        from sqlalchemy import func

        recent = self.db.execute(
            select(Memory, MemoryEmbedding.embedding)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(Memory.created_at >= func.now() - timedelta(days=3))
            .limit(400)
        ).all()
        norm = _norm(content)
        for mem, emb in recent:
            if _cos(vec, emb) >= _DEDUP_COSINE:
                text_sim = (
                    SequenceMatcher(None, norm, _norm(mem.content)).ratio()
                    if norm and mem.content
                    else 0.0
                )
                if text_sim >= _DEDUP_TEXT:
                    return mem
        return None

    def _embed_label(self) -> str:
        try:
            if self.provider.name == "gemini":
                return get_settings().gemini_embed_model
        except Exception:  # pragma: no cover
            pass
        return getattr(self.provider, "embed_model", None) or "nomic-embed-text"
