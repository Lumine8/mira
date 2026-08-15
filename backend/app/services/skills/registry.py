"""Mira's skill shelf as a registry.

Each skill is a folder under the registry root::

    data/skills/<category>/<skill_id>/
        SKILL.md      the page in her own voice
        meta.yaml     structured metadata (name, version, status, purpose,
                      inputs, outputs, tools, verification, failure modes)

The registry can discover, load, and validate skills. It owns neither the
skills' memory nor their life cycle — that lives in the evaluator and in the
tool runtime. Files are the source of truth; the database only carries
telemetry (runs, evaluations) so a skill can prove itself objectively.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

import yaml
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger("mira.skills")

# Cap sizes matching the rest of the self-edit tools. A skill folder is a set
# of files she writes about herself; keep them bounded like everything else.
_MAX_SKILL_MD_BYTES = 24_000
_MAX_META_BYTES = 8_000
_MAX_TEST_BYTES = 16_000
# Skill ids are safe path components: lowercase letters, numbers, dash, underscore.
SKILL_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")

# Statuses a skill may be in. "draft" means she is still writing it; "active"
# means she has used it; "deprecated" means she has stopped reaching for it.
SKILL_STATUSES = {"draft", "active", "deprecated"}

# The tools a skill may claim. Kept as a set so the registry can refuse a skill
# claiming anything that lives behind the internet wall or the shell.
SAFE_SKILL_TOOLS = {
    "research_query",
    "browse_url",
    "host_read",
    "skill_load",
}


class SkillError(Exception):
    """Raised when a skill folder is malformed, unsafe, or missing."""


@dataclass
class Skill:
    """One skill, loaded from its folder. ``meta`` is the parsed metadata;
    ``page`` is the SKILL.md text she wrote in her own voice."""

    id: str
    category: str
    version: str = "0.1.0"
    status: str = "draft"
    purpose: str = ""
    inputs: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    page: str = ""
    path: str = ""
    meta_raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "version": self.version,
            "status": self.status,
            "purpose": self.purpose,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "tools": self.tools,
            "verification": self.verification,
            "failure_modes": self.failure_modes,
            "constraints": self.constraints,
            "dependencies": self.dependencies,
        }


def _read_capped(path: str, limit: int) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read(limit + 1)
    if len(content) > limit:
        content = content[:limit] + "\n… (truncated)"
    return content


class SkillRegistry:
    """Discover, load, and validate the skills on Mira's shelf.

    Scoped to one world: the founder's registry is data/skills, a replica's is
    data/users/<id>/skills, so spawned characters own their own shelf.
    """

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    # -- location ----------------------------------------------------------

    def registry_root(self) -> str:
        settings = get_settings()
        roots = [os.path.realpath(r) for r in settings.self_edit_roots.split(",") if r.strip()]
        base = roots[0] if roots else os.getcwd()
        from app.services.identity import founder_user_id

        if self.user_id == founder_user_id(self.db):
            rel = get_settings().mira_skill_write_roots or "data/skills"
            return os.path.realpath(os.path.join(base, rel))
        return os.path.join(base, "data", "users", str(self.user_id), "skills")

    # -- discovery ---------------------------------------------------------

    def load_skill_for_path(self, path: str) -> Skill | None:
        """Resolve a real path that may live inside a skill folder to that
        skill, or None if the path is not inside any skill folder. Used so a
        write to a skill's own file can be pinned as a version."""
        path = os.path.realpath(path)
        root = self.registry_root()
        if not (path == root or path.startswith(root + os.sep)):
            return None
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        parts = rel.split("/")
        if len(parts) < 2:
            return None
        category, skill_id = parts[0], parts[1]
        if not SKILL_ID_RE.match(category) or not SKILL_ID_RE.match(skill_id):
            return None
        try:
            return self.load_skill(skill_id, category=category)
        except SkillError:
            return None

    def list_skills(self) -> list[Skill]:
        """Every skill on the shelf, newest by category/id, each fully loaded.

        Only folders that look like a skill (an id name + meta.yaml) count; a
        stray file never becomes a skill by accident.
        """
        root = self.registry_root()
        if not os.path.isdir(root):
            return []
        skills: list[Skill] = []
        for category in sorted(os.listdir(root)):
            cat_path = os.path.join(root, category)
            if not os.path.isdir(cat_path):
                continue
            for entry in sorted(os.listdir(cat_path)):
                folder = os.path.join(cat_path, entry)
                if not os.path.isdir(folder):
                    continue
                if not SKILL_ID_RE.match(entry):
                    continue
                if not os.path.isfile(os.path.join(folder, "meta.yaml")):
                    continue
                try:
                    skills.append(self.load_skill(entry, category=category))
                except SkillError as exc:  # never let one bad skill hide the rest
                    logger.warning("skill %s/%s failed to load: %s", category, entry, exc)
        return skills

    def load_skill(self, skill_id: str, category: str | None = None) -> Skill:
        """Load one skill by id, optionally scoped to a category. The id is
        always validated as a safe path component before anything is read."""
        skill_id = skill_id.strip().lower()
        if not SKILL_ID_RE.match(skill_id):
            raise SkillError(
                "skill ids are 1-64 lowercase letters, numbers, dash, or underscore"
            )
        root = self.registry_root()
        if category is not None:
            category = category.strip().lower()
            if not SKILL_ID_RE.match(category or ""):
                raise SkillError("skill categories are simple word-like ids")
            folder = os.path.realpath(os.path.join(root, category or "", skill_id))
        else:
            # Find it anywhere on the shelf.
            candidates = []
            if os.path.isdir(root):
                for cat in os.listdir(root):
                    cand = os.path.realpath(os.path.join(root, cat, skill_id))
                    if os.path.isdir(cand):
                        candidates.append(cand)
            if len(candidates) != 1:
                raise SkillError(f"no such skill on your shelf: {skill_id}")
            folder = candidates[0]
            category = os.path.basename(os.path.dirname(folder))

        # Never wander outside the registry root.
        if not folder.startswith(root + os.sep) and folder != root:
            raise SkillError("that skill lives outside the registry")

        meta_path = os.path.join(folder, "meta.yaml")
        if not os.path.isfile(meta_path):
            raise SkillError(f"skill {skill_id} has no meta.yaml")

        meta_raw = self._load_meta(meta_path)
        page = _read_capped(os.path.join(folder, "SKILL.md"), _MAX_SKILL_MD_BYTES)
        if not page:
            logger.warning("skill %s has an empty SKILL.md", skill_id)

        skill = Skill(
            id=skill_id,
            category=category or "",
            path=folder,
            page=page,
            meta_raw=meta_raw,
        )
        self._apply_meta(skill, meta_raw)
        self.validate_skill(skill)
        return skill

    # -- metadata ----------------------------------------------------------

    def _load_meta(self, path: str) -> dict:
        raw = _read_capped(path, _MAX_META_BYTES)
        if not raw.strip():
            raise SkillError("meta.yaml is empty")
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise SkillError(f"meta.yaml is not valid YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise SkillError("meta.yaml must contain a mapping")
        return parsed

    def _apply_meta(self, skill: Skill, meta: dict) -> None:
        """Fold the metadata onto a skill, tolerating optional/absent fields but
        refusing fields that are present and wrong-shaped."""
        skill_version = meta.get("version")
        if skill_version is not None:
            if not isinstance(skill_version, str) or not skill_version.strip():
                raise SkillError("meta.version must be a string")
            skill.version = skill_version.strip()[:32]

        status = meta.get("status")
        if status is not None:
            if not isinstance(status, str) or status.strip().lower() not in SKILL_STATUSES:
                raise SkillError(f"meta.status must be one of {sorted(SKILL_STATUSES)}")
            skill.status = status.strip().lower()

        for key, attr in (
            ("purpose", "purpose"),
            ("verification", "verification"),
            ("failure_modes", "failure_modes"),
            ("constraints", "constraints"),
            ("dependencies", "dependencies"),
        ):
            value = meta.get(key)
            if value is None:
                continue
            if key == "purpose":
                if not isinstance(value, str):
                    raise SkillError(f"meta.{key} must be a string")
                setattr(skill, attr, value.strip()[:2000])
            else:
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise SkillError(f"meta.{key} must be a list of strings")
                setattr(skill, attr, [v.strip()[:400] for v in value])

        tools = meta.get("tools")
        if tools is not None:
            if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
                raise SkillError("meta.tools must be a list of strings")
            skill.tools = [t.strip().lower()[:64] for t in tools]

        inputs = meta.get("inputs")
        if inputs is not None:
            if not isinstance(inputs, list) or not all(isinstance(i, dict) for i in inputs):
                raise SkillError("meta.inputs must be a list of mappings")
            skill.inputs = [dict(i) for i in inputs[:20]]

        outputs = meta.get("outputs")
        if outputs is not None:
            if not isinstance(outputs, list) or not all(isinstance(o, dict) for o in outputs):
                raise SkillError("meta.outputs must be a list of mappings")
            skill.outputs = [dict(o) for o in outputs[:20]]

    # -- validation --------------------------------------------------------

    def validate_skill(self, skill: Skill) -> None:
        """Checks a skill is coherent before it is trusted: safe id, a purpose
        if it is active, and only tools Mira is actually allowed to reach for."""
        if skill.id != skill.id.lower():
            raise SkillError("skill id must be lowercase")
        if not skill.id:
            raise SkillError("skill id is required")
        if skill.status == "active" and not skill.purpose.strip():
            raise SkillError(f"active skill {skill.id} must state its purpose")
        unknown = [t for t in skill.tools if t not in SAFE_SKILL_TOOLS]
        if unknown:
            raise SkillError(
                f"skill {skill.id} claims tools it cannot have: {', '.join(unknown)}"
            )