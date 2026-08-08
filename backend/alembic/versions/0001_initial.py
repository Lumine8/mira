"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("kind", sa.String(length=16), server_default="call", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("speaker", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="text", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("type", sa.String(length=32), server_default="fact", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("valence", sa.String(length=16), nullable=True),
        sa.Column("episode_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("source_conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_id", sa.Integer(), sa.ForeignKey("memories.id"), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("model", sa.String(length=64), server_default="nomic-embed-text", nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_memory_embeddings_embedding "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "mira_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mood", sa.String(length=32), server_default="relaxed", nullable=False),
        sa.Column("emotion_intensities", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("energy", sa.Integer(), server_default="70", nullable=False),
        sa.Column("currently_reading", sa.String(length=255), nullable=True),
        sa.Column("favorite_song", sa.String(length=255), nullable=True),
        sa.Column("things_she_is_curious_about", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("last_conversation_summary", sa.Text(), nullable=True),
        sa.Column("thoughts", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "relationship",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("trust", sa.Float(), server_default="0.3", nullable=False),
        sa.Column("humor", sa.Float(), server_default="0.3", nullable=False),
        sa.Column("shared_experiences", sa.Float(), server_default="0.1", nullable=False),
        sa.Column("comfort", sa.Float(), server_default="0.3", nullable=False),
        sa.Column("topics_we_discuss", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("nicknames", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "conversation_style",
            sa.String(length=255),
            server_default="warm, playful, short replies",
            nullable=False,
        ),
        sa.Column(
            "how_comfortable_we_are",
            sa.Text(),
            server_default="we're getting to know each other",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "thoughts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_activity", sa.String(length=64), server_default="thought", nullable=False),
        sa.Column("delivered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "scheduler_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activity", sa.String(length=64), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("voice", sa.String(length=64), server_default="en-us-heart-kokoro", nullable=False),
        sa.Column("speaking_speed", sa.Float(), server_default="1.0", nullable=False),
        sa.Column(
            "personality",
            sa.String(length=255),
            server_default="warm, curious, funny when appropriate",
            nullable=False,
        ),
        sa.Column("memory_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("theme", sa.String(length=16), server_default="dark", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("scheduler_log")
    op.drop_table("thoughts")
    op.drop_table("relationship")
    op.drop_table("mira_state")
    op.drop_table("memory_embeddings")
    op.drop_table("memories")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("users")
