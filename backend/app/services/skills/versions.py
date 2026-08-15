"""The self-improvement loop — how a skill's own files change over time.

The registry's files are the source of truth; this service is the history that
makes her growth reviewable. Every time one of a skill's files is written, the
before and after are captured side by side, so a change can be shown as a diff
and reverted if it made the skill worse. A skill improves the same way a person
does: by editing, looking at what changed, and keeping what works.
"""

from __future__ import annotations

import difflib
import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SkillVersion
from app.services.skills.registry import SkillRegistry

logger = logging.getLogger("mira.skills.versions")


class SkillVersionError(Exception):
    """Raised when a version is missing, not owned, or outside the registry."""


def _diff_lines(before: str | None, after: str | None) -> list[dict]:
    """A small, readable diff between two file states: removed lines first,
    then added lines, each tagged so the shelf can render them honestly."""
    before_lines = (before or "").splitlines(keepends=False)
    after_lines = (after or "").splitlines(keepends=False)
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for line in before_lines[i1:i2]:
            out.append({"tag": "removed", "line": line})
        for line in after_lines[j1:j2]:
            out.append({"tag": "added", "line": line})
    return out[:200]


class SkillVersionService:
    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    def record(
        self,
        skill,
        *,
        path: str,
        before: str | None,
        after: str,
        reason: str = "",
        change_id: int | None = None,
        kind: str = "edit",
    ) -> SkillVersion:
        """Pin one edit to a skill's file: the file path, its before and after,
        and why it happened. ``change_id`` ties it to the pending change that
        carried the edit, so the version history and the approval ledger agree."""
        version = SkillVersion(
            user_id=self.user_id,
            skill_id=skill.id,
            category=skill.category,
            version=skill.version,
            kind=kind,
            path=path[:255],
            reason=reason[:2000],
            change_id=change_id,
            before_content=before,
            after_content=after,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        return version

    def list_for(self, skill_id: str, *, category: str | None = None, limit: int = 50) -> list[SkillVersion]:
        """The edit history of one skill, newest first."""
        q = select(SkillVersion).where(SkillVersion.user_id == self.user_id, SkillVersion.skill_id == skill_id)
        if category:
            q = q.where(SkillVersion.category == category)
        q = q.order_by(SkillVersion.created_at.desc(), SkillVersion.id.desc()).limit(limit)
        return list(self.db.execute(q).scalars())

    def get(self, version_id: int, *, skill_id: str) -> SkillVersion:
        version = self.db.get(SkillVersion, version_id)
        if version is None or version.user_id != self.user_id or version.skill_id != skill_id:
            raise SkillVersionError(f"no such version #{version_id} for skill {skill_id}")
        return version

    def as_dict(self, version: SkillVersion, *, include_diff: bool = False) -> dict:
        data = {
            "id": version.id,
            "skill_id": version.skill_id,
            "category": version.category,
            "version": version.version,
            "kind": version.kind,
            "path": version.path,
            "reason": version.reason,
            "change_id": version.change_id,
            "created_at": version.created_at,
        }
        if include_diff:
            data["diff"] = _diff_lines(version.before_content, version.after_content)
            data["after_content"] = version.after_content
        return data

    def revert(self, skill, version: SkillVersion, *, registry: SkillRegistry) -> SkillVersion:
        """Put a skill's file back to how it was before this version, and pin
        that as a version of its own (kind ``revert``) so the loop is complete:
        edit → diff → revert → new history entry."""
        if version.kind == "revert":
            raise SkillVersionError("that version is itself a revert; there is nothing to go back to")
        if not version.before_content:
            raise SkillVersionError("this version created the file — reverting would delete it")

        # Resolve the skill's folder so the file is written back inside the
        # registry and nowhere else. skill.path is the folder itself.
        base = os.path.realpath(skill.path)
        target = os.path.realpath(os.path.join(base, version.path))
        if not target.startswith(base + os.sep):
            raise SkillVersionError("that file lives outside the skill's folder")

        with open(target, "w", encoding="utf-8") as fh:
            fh.write(version.before_content)

        return self.record(
            skill,
            path=version.path,
            before=version.after_content,
            after=version.before_content,
            reason=f"reverted to before edit #{version.id}",
            kind="revert",
        )
