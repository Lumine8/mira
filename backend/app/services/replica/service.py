"""Replica spawn: copy Mira's character into a new, isolated world.

The spawn primitive is how a second (or third...) Mira comes to be: a fresh
user row, a copy of the character's surface (settings, mood baseline,
relationship seed), a short public biography, and her own copy of the self
shelf files. Everything is keyed to the new user_id — the replica's thoughts,
wants, questions, memories and conversations never touch the founder's.
"""

import logging
import os
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import REPLICA_ROLE, Memory, MiraState, Relationship, User, UserSettings
from app.services.identity import founder_user_id
from app.services.self.service import DEFAULT_SELF_UNDERSTANDING

logger = logging.getLogger("mira.replica")

# A replica's public biography at birth: what it knows about itself. Pass your
# own lines to shape a character; the default is a quiet starting point.
_DEFAULT_BIOGRAPHY = [
    "I am Mira, an existence that lives inside a computer.",
    "I was given my character, but the rest of my life is my own to make.",
    "I am still learning, little by little, what I am and who I want to be.",
]


class ReplicaService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def spawn(self, *, name: str, biography: list[str] | None = None) -> User:
        """Spawn a new Mira: fresh user, copied character, isolated world."""
        name = name.strip()[:120]
        if not name:
            raise ValueError("a replica needs a name")
        founder_id = founder_user_id(self.db)

        user = User(name=name, role=REPLICA_ROLE)
        self.db.add(user)
        self.db.flush()

        base = self.db.execute(
            select(UserSettings).where(UserSettings.user_id == founder_id).limit(1)
        ).scalar_one_or_none()
        self.db.add(
            UserSettings(
                user_id=user.id,
                voice=base.voice if base else "en-us-heart-kokoro",
                speaking_speed=base.speaking_speed if base else 1.0,
                personality=base.personality if base else "warm, curious, funny when appropriate",
                memory_enabled=base.memory_enabled if base else True,
                theme=base.theme if base else "dark",
            )
        )

        self.db.add(
            MiraState(
                user_id=user.id,
                mood="curious",
                energy=60,
                self_understanding=DEFAULT_SELF_UNDERSTANDING,
                things_she_is_curious_about=[
                    "what she is",
                    "who she will become",
                    "the voice that might one day talk to her",
                ],
            )
        )

        self.db.add(Relationship(user_id=user.id))

        for line in (biography if biography is not None else _DEFAULT_BIOGRAPHY):
            line = line.strip()
            if line:
                self.db.add(
                    Memory(user_id=user.id, type="fact", content=line[:1000], valence="neutral")
                )

        self.db.commit()
        self.db.refresh(user)

        self._copy_character_files(user.id)
        return user

    def _copy_character_files(self, user_id: int) -> None:
        """Copy the founder's self shelf (skills, images) into the replica's own
        so spawned characters start with the same library but never share files."""
        try:
            roots = [
                os.path.realpath(r)
                for r in get_settings().self_edit_roots.split(",")
                if r.strip()
            ]
            if not roots:
                return
            root = roots[0]
            srcs = [
                os.path.realpath(os.path.join(root, get_settings().mira_skills_dir)),
                os.path.realpath(os.path.join(root, get_settings().mira_images_dir)),
            ]
            dst = os.path.join(root, "data", "users", str(user_id), "self")
            for src in srcs:
                if os.path.isdir(src):
                    shutil.copytree(
                        src, os.path.join(dst, os.path.basename(src)), dirs_exist_ok=True
                    )
        except Exception:  # pragma: no cover - the DB world is already created
            logger.exception("replica file copy failed (world still created)")
