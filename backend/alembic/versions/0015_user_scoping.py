"""user scoping: every world row belongs to a user; founder seeded

Revision ID: 0015_user_scoping
Revises: 0014_mote
Create Date: 2026-08-11

Phase 1 data foundation. Every row that forms a user's world gets a user_id
foreign key and index, existing rows are backfilled to the founder, and the
columns are promoted to NOT NULL so no future row can drift un-owned. The
founder user (the original owner's seat, id of the first/only user, created as
'voice' on a fresh database) is seeded so backfill always has a home.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_user_scoping"
down_revision: Union[str, None] = "0014_mote"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New scoping columns: added, backfilled, then made NOT NULL + FK + index.
# scheduler_log is pure diagnostics (never user-facing) so it stays nullable.
_NEW_SCOPED = [
    "mira_state",
    "thoughts",
    "mood_history",
    "perceived_events",
    "pending_changes",
    "wants",
    "questions",
    "mote_shared_time",
    "x_auth",
]
_DIAGNOSTIC = ["scheduler_log"]

# Already had user_id (nullable, no index); promote + index.
# conversations/memories already carry an FK; relationship/settings do not.
_EXISTING_WITH_FK = ["conversations", "memories"]
_EXISTING_NO_FK = ["relationship", "settings"]


def _backfill(bind, table: str, founder_id: int) -> None:
    bind.execute(
        sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
        {"uid": founder_id},
    )


def upgrade() -> None:
    bind = op.get_bind()

    # -- 1. users.role + founder seed ---------------------------------------
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="replica"),
    )
    founder_id = bind.execute(
        sa.text("SELECT id FROM users WHERE role = 'founder' ORDER BY id LIMIT 1")
    ).scalar()
    if founder_id is None:
        first = bind.execute(
            sa.text("SELECT id FROM users ORDER BY id LIMIT 1")
        ).scalar()
        if first is not None:
            # The original owner's seat becomes the founder.
            bind.execute(
                sa.text("UPDATE users SET role = 'founder' WHERE id = :i"), {"i": first}
            )
            founder_id = first
        else:
            founder_id = bind.execute(
                sa.text(
                    "INSERT INTO users (name, role) VALUES ('voice', 'founder') RETURNING id"
                )
            ).scalar()

    # -- 2. new scoping columns ---------------------------------------------
    for table in _NEW_SCOPED:
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        _backfill(bind, table, founder_id)
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_user_id_users", table, "users", ["user_id"], ["id"]
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    for table in _DIAGNOSTIC:
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        _backfill(bind, table, founder_id)
        op.create_foreign_key(
            f"fk_{table}_user_id_users", table, "users", ["user_id"], ["id"]
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    # -- 3. promote existing columns ----------------------------------------
    for table in _EXISTING_WITH_FK:
        _backfill(bind, table, founder_id)
        op.alter_column(table, "user_id", nullable=False)
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    for table in _EXISTING_NO_FK:
        _backfill(bind, table, founder_id)
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_user_id_users", table, "users", ["user_id"], ["id"]
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def downgrade() -> None:
    for table in _NEW_SCOPED + _DIAGNOSTIC + _EXISTING_NO_FK:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_user_id_users", table, type_="foreignkey")
    for table in _EXISTING_WITH_FK:
        op.drop_index(f"ix_{table}_user_id", table_name=table)

    for table in _NEW_SCOPED + _DIAGNOSTIC:
        op.drop_column(table, "user_id")
    for table in _EXISTING_NO_FK + _EXISTING_WITH_FK:
        op.alter_column(table, "user_id", nullable=True)

    op.drop_column("users", "role")
