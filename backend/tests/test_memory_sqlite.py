import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Memory, MemoryEmbedding, User
from app.services.memory.service import MemoryService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Memory.__table__.create(engine)
    MemoryEmbedding.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class _EmbedProvider:
    async def embed(self, text: str) -> list[float]:
        # Cheap bag-of-words embedding so similarity is deterministic.
        words = "mira rain evening window sky book".split()
        import hashlib

        vec = [0.0] * 32
        for token in text.lower().split():
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % 32
            vec[idx] += 1.0
        return vec


def _seed(db, content: str, *, user_id: int = 1) -> None:
    mem = Memory(type="fact", content=content, user_id=user_id)
    db.add(mem)
    db.flush()
    embedding = asyncio.run(_EmbedProvider().embed(content))
    db.add(MemoryEmbedding(memory_id=mem.id, embedding=embedding))
    db.commit()


class _SqliteSettings:
    is_sqlite = True


def test_sqlite_recall_ranks_by_cosine(db, monkeypatch) -> None:
    monkeypatch.setattr("app.services.memory.service.get_settings", lambda: _SqliteSettings())
    _seed(db, "the rain decides nothing at all")
    _seed(db, "mira watches the evening light")
    _seed(db, "the voice reads a book by the window")

    results = asyncio.run(MemoryService(db, _EmbedProvider(), user_id=1).recall("evening light", k=2))
    contents = [r["content"] for r in results]
    assert contents[0] == "mira watches the evening light"


def test_sqlite_recall_does_not_need_pgvector(db, monkeypatch) -> None:
    # The in-memory model layer stores embeddings as JSON, so recall must not
    # call the pgvector cosine_distance SQL (which would fail on sqlite).
    monkeypatch.setattr("app.services.memory.service.get_settings", lambda: _SqliteSettings())
    svc = MemoryService(db, _EmbedProvider(), user_id=1)
    results = asyncio.run(svc.recall("no memories yet", k=5))
    assert results == []