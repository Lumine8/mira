"""fix embedding dim to 768 (nomic-embed-text)

Revision ID: 0003_embedding_dim_768
Revises: 0002_self_understanding
Create Date: 2026-08-02

"""
from collections.abc import Sequence

from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0003_embedding_dim_768"
down_revision: str | None = "0002_self_understanding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_memory_embeddings_embedding", table_name="memory_embeddings")
    op.alter_column(
        "memory_embeddings",
        "embedding",
        type_=Vector(768),
        existing_type=Vector(384),
        existing_nullable=False,
    )
    op.execute(
        "CREATE INDEX ix_memory_embeddings_embedding "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_embedding", table_name="memory_embeddings")
    op.alter_column(
        "memory_embeddings",
        "embedding",
        type_=Vector(384),
        existing_type=Vector(768),
        existing_nullable=False,
    )
    op.execute(
        "CREATE INDEX ix_memory_embeddings_embedding "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )
