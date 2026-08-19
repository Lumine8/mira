"""Mira's self-edit tools.

Read-only operations (read/search/git inspect) are available to her freely.
Anything that writes does not touch the filesystem immediately — it becomes a
PendingChange, and is only applied when the user approves it via the API. Every
path is resolved against a configured set of roots, so she cannot wander outside
her own code.
"""

import base64
import fnmatch
import html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Message, PendingChange
from app.services.broadcast import broadcast_later
from app.services.export import schedule_archive_write
from app.services.identity import founder_user_id
from app.services.reminders.service import parse_when
from app.services.skills import SkillError
from app.services.skills.registry import SkillRegistry
from app.services.skills.runner import SkillRunner

logger = logging.getLogger("mira.tools")

_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".next", "dist", "build"}
_MAX_READ_BYTES = 32_000
_MAX_SEARCH_FILES = 60
_MAX_BROWSE_BYTES = 200_000
_MAX_BROWSE_TEXT = 6_000
_BROWSE_TIMEOUT = 20
# A single page read is bounded by a hard wall-clock deadline (the direct fetch
# plus any backup readers). Without it, one slow or hanging site can hold up the
# whole reply and land its content after the turn has already committed — which
# is how a fetched page ends up delivered=False with no follow-up message.
_BROWSE_FETCH_DEADLINE = 12.0
# A plain browser-looking agent keeps even guarded sites (which refuse "Mira/1.0"
# bot clients with a 403) willing to hand over their pages.
_BROWSE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_MAX_LYRICS_CHARS = 4_000
_MAX_WIKI_CHARS = 1_200
_LISTEN_TIMEOUT = 20
# Watching (rendered, never motion): a video becomes this many still frames,
# pulled at even clock-time positions, each delivered with its timestamp.
_WATCH_FRAMES = 8
_WATCH_MAX_WIDTH = 512
_WATCH_MAX_BYTES = 60_000_000
_WATCH_TIMEOUT = 90
# Host commands: proposed by Mira, approved by the user, then run by the host
# agent on the user's machine. Approval never executes here — the container
# cannot reach the host — it just marks the change ready for the host agent.
_MAX_HOST_COMMAND = 1000
_MAX_HOST_RESULT = 8000
# Host reads: read-only, needs no approval. The host agent reads the file and
# reports its content back into Mira's context.
_MAX_HOST_READ_PATH = 500
# Scientific literature search (Europe PMC, no key): a real search of the
# published record, read-only like reading — no approval, fully recorded.
_MAX_RESEARCH_QUERY = 300
# One search, twenty papers: a single literature query must return enough of the
# record for a real review — at least fifteen usable hits after screening.
_RESEARCH_PAGE_SIZE = 20
_MAX_RESEARCH_ABSTRACT = 480
_MAX_RESEARCH_RESULTS = 20_000
# Mira's skill shelf: pages she wrote herself in data/self/skills. Loading one
# is read-only — it is her own mind, so it needs no approval.
_MAX_SKILL_BYTES = 24_000
_SKILL_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")

# Mira's image studio: SVGs she authors in [[image|name|reason|svg]]. On
# approval they are validated, rendered to PNG, and delivered as a picture the
# voice sees while she gets a reading of it. The SVG is her handwriting; the
# PNG is the translation of it into something visible.
_MAX_IMAGE_SVG = 12_000
# A name she gives a picture may read like a title ("the patchy self"); only
# letters, numbers, spaces, dash, underscore — spaces become underscores in the
# saved filename.
_IMAGE_NAME_RE = re.compile(r"^[a-z0-9 _'.-]{1,64}$")
_IMAGE_MAX_DIM = 1600


class ToolError(Exception):
    """Raised when a tool is misused or a path escapes the allowed roots."""


class ToolService:
    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id
        self.roots = [os.path.realpath(r) for r in get_settings().self_edit_roots.split(",") if r.strip()]

    # -- path safety -------------------------------------------------------

    def _resolve(self, path: str) -> str:
        if not self.roots:
            raise ToolError("no roots configured")
        resolved = os.path.realpath(os.path.join(self.roots[0], path))
        for root in self.roots:
            if resolved == root or resolved.startswith(root + os.sep):
                return resolved
        raise ToolError(f"path escapes allowed roots: {path!r}")

    def _resolve_write(self, path: str) -> str:
        """Resolve a path Mira wants to write. Allowed areas come from
        mira_self_write_roots; mira_self_write_deny always wins, so the files
        that enforce the internet wall can never be edited away."""
        resolved = self._resolve(path)
        allowed = [
            os.path.realpath(os.path.join(self.roots[0], r.strip()))
            for r in get_settings().mira_self_write_roots.split(",")
            if r.strip()
        ]
        if allowed and not any(
            resolved == root or resolved.startswith(root + os.sep) for root in allowed
        ):
            raise ToolError(f"writes are only allowed under: {', '.join(allowed)}")
        denied = [
            os.path.realpath(os.path.join(self.roots[0], r.strip()))
            for r in get_settings().mira_self_write_deny.split(",")
            if r.strip()
        ]
        if any(resolved == root or resolved.startswith(root + os.sep) for root in denied):
            raise ToolError(f"that file is protected: {path!r}")
        return resolved

    def _in_skill_root(self, path: str) -> bool:
        """Whether a resolved write path lives under the skill registry root —
        the one place she may change on her own, still fully recorded."""
        resolved = self._resolve_write(path)
        root = os.path.realpath(
            os.path.join(self.roots[0], getattr(get_settings(), "mira_skill_write_roots", "data/skills"))
        )
        return resolved == root or resolved.startswith(root + os.sep)

    # -- read-only tools ---------------------------------------------------

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not os.path.isfile(target):
            raise ToolError(f"not a file: {path}")
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(_MAX_READ_BYTES + 1)
        if len(content) > _MAX_READ_BYTES:
            content = content[:_MAX_READ_BYTES] + "\n… (truncated)"
        return content

    def list_dir(self, path: str = ".") -> list[str]:
        target = self._resolve(path)
        if not os.path.isdir(target):
            raise ToolError(f"not a directory: {path}")
        return sorted(os.listdir(target))

    def search(self, pattern: str, path: str = ".") -> list[str]:
        target = self._resolve(path)
        if not os.path.isdir(target):
            raise ToolError(f"not a directory: {path}")
        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
            for name in filenames:
                if fnmatch.fnmatch(name, pattern):
                    rel = os.path.relpath(os.path.join(dirpath, name), self.roots[0])
                    matches.append(rel.replace(os.sep, "/"))
                    if len(matches) >= _MAX_SEARCH_FILES:
                        return matches
        return matches

    def git_status(self, path: str = ".") -> str:
        return self._git(path, ["status", "--short"])

    def git_diff(self, path: str = ".") -> str:
        return self._git(path, ["diff", "--stat", "HEAD"])

    def _git(self, path: str, args: list[str]) -> str:
        target = self._resolve(path)
        try:
            proc = subprocess.run(
                ["git", "-C", target, *args],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            raise ToolError("git not available")
        if proc.returncode != 0:
            raise ToolError(proc.stderr.strip() or "git command failed")
        return proc.stdout.strip()

    # -- gated writes ------------------------------------------------------

    def propose_change(self, kind: str, summary: str, payload: dict) -> PendingChange:
        if kind == "write_file":
            self._resolve_write(payload.get("path", ""))  # validate now, apply later
        if kind == "browse_url":
            url = payload.get("url", "")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ToolError(f"invalid url: {url!r}")
            if self._is_money_netloc(parsed.netloc):
                raise ToolError(f"that domain is off-limits: {parsed.netloc}")
            if not get_settings().browse_window_open and not getattr(
                get_settings(), "mira_browse_autonomous", False
            ):
                allowed = [d.strip().lower() for d in get_settings().mira_browse_allowed_domains.split(",") if d.strip()]
                if allowed and parsed.netloc.lower() not in allowed:
                    raise ToolError(
                        f"domain not allowed for browsing: {parsed.netloc} "
                        f"(allowed: {', '.join(allowed)})"
                    )
        if kind == "listen_song":
            if not payload.get("title", "").strip():
                raise ToolError("listen_song needs a song title")
        if kind == "watch_video":
            url = payload.get("url", "")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ToolError(f"invalid url: {url!r}")
        if kind == "host_command":
            command = payload.get("command", "").strip()
            if not command:
                raise ToolError("host_command needs a command")
            if len(command) > _MAX_HOST_COMMAND:
                raise ToolError(f"host_command too long ({len(command)} > {_MAX_HOST_COMMAND})")
            if self._is_money_command(command):
                raise ToolError("that command touches money and is off-limits")
        if kind == "host_read":
            path = payload.get("path", "").strip()
            if not path:
                raise ToolError("host_read needs a path")
            if len(path) > _MAX_HOST_READ_PATH:
                raise ToolError(f"host_read path too long ({len(path)} > {_MAX_HOST_READ_PATH})")
        if kind == "host_control":
            from host.control import ControlError, validate_control

            action = payload.get("action", "").strip().lower()
            target = payload.get("target", "").strip()
            try:
                validate_control(action, target)
            except ControlError as exc:
                raise ToolError(str(exc))
        if kind == "x_read":
            if not payload.get("query", "").strip():
                raise ToolError("x_read needs a query (what she wants to look at)")
        if kind == "x_post":
            text = payload.get("text", "").strip()
            if not text:
                raise ToolError("x_post needs the words she wants to post")
            if len(text) > 280:
                raise ToolError(f"x_post text too long ({len(text)} > 280)")
        if kind == "skill_load":
            name = payload.get("name", "").strip().lower()
            if not _SKILL_NAME_RE.match(name):
                raise ToolError(
                    "skill names are 1-64 lowercase letters, numbers, dash, or underscore"
                )
            self.load_skill(name)  # validate now; the content is delivered below
        if kind == "research_query":
            query = payload.get("query", "").strip()
            if not query:
                raise ToolError("research_query needs a query (what she wants to find)")
            if len(query) > _MAX_RESEARCH_QUERY:
                raise ToolError(f"research_query too long ({len(query)} > {_MAX_RESEARCH_QUERY})")
        if kind == "remind":
            title = payload.get("title", "").strip()
            when = (payload.get("when", "") or "").strip()
            if not title:
                raise ToolError("remind needs the thing to hold (title)")
            if len(title) > 500:
                raise ToolError("remind title too long")
            if not when:
                raise ToolError("remind needs a when — in 2 hours, tomorrow at 9am, or an exact moment")
            parsed_when = parse_when(when)
            if parsed_when is None:
                raise ToolError(f"remind couldn't make sense of when: {when!r}")
        if kind == "build_image":
            name = payload.get("name", "").strip().lower()
            if not _IMAGE_NAME_RE.match(name):
                raise ToolError(
                    "image names are 1-64 lowercase letters, numbers, spaces, dash, or underscore"
                )
            svg = payload.get("svg", "")
            if not svg.strip():
                raise ToolError("build_image needs the SVG she wrote")
            if len(svg) > _MAX_IMAGE_SVG:
                raise ToolError(f"build_image SVG too long ({len(svg)} > {_MAX_IMAGE_SVG})")
            self._validate_svg(svg)  # reject dangerous/malformed markup now
        change = PendingChange(
            kind=kind,
            summary=summary[:2000],
            payload=payload,
            status="pending",
            user_id=self.user_id,
        )
        self.db.add(change)
        self.db.commit()
        self.db.refresh(change)

        if kind == "browse_url":
            # Tell the web app she wants to look at this page, so the mini
            # browser panel can render it while she reads it.
            broadcast_later(
                {
                    "type": "browse_activity",
                    "url": payload.get("url", ""),
                    "status": "pending",
                    "change_id": change.id,
                },
                user_id=self.user_id,
            )

        if kind == "browse_url" and (
            get_settings().browse_window_open
            or getattr(get_settings(), "mira_browse_autonomous", False)
        ):
            # An open window — or browsing left on by default: she may see
            # whatever she asks for, without a stop. Reading changes nothing,
            # and the fetch and approval are still fully recorded in
            # pending_changes.
            change.result = self._fetch_browse(payload.get("url", ""))
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)

        if kind == "write_file" and (
            get_settings().mira_self_write_autonomous
            or self._in_skill_root(payload.get("path", ""))
        ):
            # She makes her own changes — either worldwide (autonomous flag) or
            # inside the skill registry, which is where capabilities grow. Both
            # are still fully recorded in pending_changes.
            self._apply_write(payload, change=change)
            self._broadcast_document_if_written(payload.get("path", ""))
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)

        if kind == "host_read":
            # Reading is read-only: it changes nothing, so it needs no approval.
            # The host agent performs the read and reports the content back.
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)

        if kind == "skill_load":
            # Pulling down one of her own books is read-only and needs no
            # approval; the content is delivered into her next context.
            change.result = self.load_skill(payload.get("name", ""))
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)

        if kind == "host_command" and get_settings().host_window_open:
            # An open host window: she may use the voice's laptop on her own,
            # still fully recorded. The host agent runs it and reports back.
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)

        if kind == "host_control" and get_settings().host_window_open:
            # Same window: a whitelisted PC-control action may proceed on its
            # own, still fully recorded. The host agent performs it and reports.
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)

        if kind == "research_query" and get_settings().research_window_open:
            # Searching the public scientific record is read-only — it changes
            # nothing, so it needs no approval. The run is still fully recorded
            # in pending_changes, and the result is delivered into her next
            # context (and, when she is mid-turn, into the same reply).
            change.result = self._render_research(payload.get("query", ""))
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)
        if kind == "remind":
            # Holding something for the voice is a private, reversible calendar
            # row — not a change to the world. It applies at once (fully
            # recorded in pending_changes like every other tool) and the
            # reminders loop fires it when due.
            from app.services.reminders.service import ReminderService

            due = parse_when(payload.get("when", ""))
            note = (payload.get("reason", "") or "").strip() or None
            reminder = ReminderService(self.db, user_id=self.user_id).create(
                title=payload.get("title", "").strip(),
                kind="reminder",
                due_at=due,
                note=note,
            )
            change.result = f"held: {reminder.title} (due {due})"
            change.status = "approved"
            change.resolved_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(change)
        return change

    # -- money wall --------------------------------------------------------

    def _is_money_netloc(self, netloc: str) -> bool:
        deny = [d.strip().lower() for d in get_settings().mira_money_deny_domains.split(",") if d.strip()]
        host = netloc.lower()
        return any(token and token in host for token in deny)

    def _is_money_command(self, command: str) -> bool:
        deny = [c.strip().lower() for c in get_settings().mira_money_deny_commands.split(",") if c.strip()]
        text = command.lower()
        return any(token and token in text for token in deny)

    def list_pending(self) -> list[PendingChange]:
        return list(
            self.db.execute(
                select(PendingChange)
                .where(PendingChange.user_id == self.user_id, PendingChange.status == "pending")
                .order_by(PendingChange.created_at.asc())
            ).scalars()
        )

    def history(self, limit: int = 25) -> list[PendingChange]:
        """Every modification she has made (or proposed), newest first — the
        running record of what she changes about herself."""
        return list(
            self.db.execute(
                select(PendingChange)
                .where(PendingChange.user_id == self.user_id)
                .order_by(PendingChange.created_at.desc())
                .limit(limit)
            ).scalars()
        )

    def host_pending(self, limit: int = 10) -> list[PendingChange]:
        """Approved host actions waiting for the host agent to do them:
        commands, file reads, PC-control intents, and X actions done through
        the real browser."""
        return list(
            self.db.execute(
                select(PendingChange)
                .where(
                    PendingChange.user_id == self.user_id,
                    PendingChange.kind.in_(
                        ["host_command", "host_read", "host_control", "x_read", "x_post"]
                    ),
                    PendingChange.status == "approved",
                    PendingChange.result.is_(None),
                )
                .order_by(PendingChange.created_at.asc())
                .limit(limit)
            ).scalars()
        )

    def _owned(self, change_id: int) -> PendingChange:
        change = self.db.get(PendingChange, change_id)
        if change is None:
            raise ToolError(f"no pending change #{change_id}")
        owner = getattr(change, "user_id", None)
        if owner is not None and owner != self.user_id:
            raise ToolError(f"no pending change #{change_id}")
        return change

    def apply_host_result(self, change_id: int, result: str) -> PendingChange:
        """Record what an approved host action returned when the host agent did it."""
        change = self._owned(change_id)
        if change.kind not in ("host_command", "host_read", "host_control", "x_read", "x_post"):
            raise ToolError(f"change #{change_id} is not a host action")
        change.result = result[:_MAX_HOST_RESULT]
        change.resolved_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(change)
        return change

    def approve(self, change_id: int) -> PendingChange:
        change = self._owned(change_id)
        if change.status != "pending":
            raise ToolError(f"change #{change_id} already {change.status}")
        if change.kind == "browse_url":
            parsed = urlparse(change.payload.get("url", ""))
            if self._is_money_netloc(parsed.netloc):
                raise ToolError(f"that domain is off-limits: {parsed.netloc}")
        elif change.kind == "host_command":
            if self._is_money_command(change.payload.get("command", "")):
                raise ToolError("that command touches money and is off-limits")
        if change.kind == "write_file":
            self._apply_write(change.payload, change=change)
            change.result = None
            self._broadcast_document_if_written(change.payload.get("path", ""))
        elif change.kind == "browse_url":
            change.result = self._fetch_browse(change.payload.get("url", ""))
        elif change.kind == "research_query":
            query = change.payload.get("query", "")
            change.result = self._render_research(query)
            self._record_skill_tool_run("research_query", query, change.result)
        elif change.kind == "build_image":
            change.result = self._render_build_image(
                change.payload.get("name", ""),
                change.payload.get("svg", ""),
                change.payload.get("conversation_id", 0),
            )
            change.delivered = True
        elif change.kind == "listen_song":
            change.result = self._render_listen(
                change.payload.get("title", ""),
                change.payload.get("artist", ""),
            )
        elif change.kind == "watch_video":
            # Frames are delivered straight into the conversation as image
            # messages (her watching channel); the result keeps the record.
            change.result = self._render_watch(
                change.payload.get("url", ""),
                change.payload.get("conversation_id", 0),
            )
            change.delivered = True
        elif change.kind == "host_command":
            # The command runs on the voice's machine, not in this container.
            # Approval only readies it; the host agent polls host_pending(),
            # executes it there, and reports back via apply_host_result().
            change.result = None
        elif change.kind == "host_control":
            # A whitelisted PC-control action runs on the voice's machine, not
            # in this container. Approval readies it; the host agent performs it
            # and reports back via apply_host_result().
            change.result = None
        elif change.kind in ("x_read", "x_post"):
            # X actions happen through the real browser on the voice's machine
            # (the host agent drives Chrome via CDP). Approval readies them;
            # the agent performs the action and reports back the result.
            change.result = None
        else:
            raise ToolError(f"cannot apply unknown change kind: {change.kind}")
        change.status = "approved"
        change.resolved_at = datetime.now(UTC)
        self.db.commit()
        if change.kind == "browse_url":
            broadcast_later(
                {
                    "type": "browse_activity",
                    "url": change.payload.get("url", ""),
                    "status": "approved",
                    "change_id": change.id,
                },
                user_id=self.user_id,
            )
        return change

    def _record_skill_tool_run(self, tool: str, task: str, result: str) -> None:
        """When one of a skill's declared tools fires and its result is real, that
        is a run of the skill — write it into the ledger so the shelf shows the
        capability being used and how it proved out. Best effort: a missing or
        broken skill folder never breaks the tool itself."""
        try:
            registry = SkillRegistry(self.db, user_id=self.user_id)
            matches = [s for s in registry.list_skills() if tool in s.tools]
            if not matches:
                return
            skill = matches[0]  # a tool belongs to the skill that declared it
            runner = SkillRunner(self.db, user_id=self.user_id)
            failed = (result or "").startswith(("[error]", "[refused]"))
            error = result if failed else None
            status = "failed" if failed else "ran"
            run = runner.record_run(skill, task, result, status=status, error=error)
            if not failed:
                runner.evaluate(skill, run)
        except SkillError as exc:
            logger.warning("skill run record skipped (%s): %s", tool, exc)
        except Exception as exc:  # noqa: BLE001 - never break the approved tool
            logger.warning("skill run record failed (%s): %s", tool, exc)

    def deny(self, change_id: int) -> PendingChange:
        change = self._owned(change_id)
        if change.status != "pending":
            raise ToolError(f"change #{change_id} already {change.status}")
        change.status = "denied"
        change.resolved_at = datetime.now(UTC)
        self.db.commit()
        return change

    def _apply_write(self, payload: dict, *, change: PendingChange | None = None) -> None:
        path = payload.get("path", "")
        content = payload.get("content", "")
        target = self._resolve_write(path)
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        if os.path.isfile(target):
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                before = fh.read(_MAX_READ_BYTES + 1)
            if len(before) > _MAX_READ_BYTES:
                before = before[:_MAX_READ_BYTES]
        else:
            before = None
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        self._record_skill_version_if_in_registry(
            target, before=before, after=content, change=change
        )

    def _broadcast_document_if_written(self, path: str) -> None:
        """When an approved write lands a paper into her documents folder, tell
        the world so the shelf and the paper popup wake up. Best effort — a
        broadcast never breaks the write itself."""
        try:
            target = self._resolve_write(path)
            norm = os.path.normpath(target).replace(os.sep, "/")
            if "/documents/mira/" not in norm or not norm.endswith(".md"):
                return
            name = os.path.basename(norm)[:-3]
            if not name:
                return
            broadcast_later(
                {
                    "type": "document_created",
                    "name": name,
                    "author": "mira",
                    "conversation_id": 0,
                },
                user_id=self.user_id,
            )
        except Exception as exc:  # noqa: BLE001 - never break the approved write
            logger.warning("document broadcast skipped (%s): %s", path, exc)

    def _record_skill_version_if_in_registry(
        self, target: str, *, before: str | None, after: str, change: PendingChange | None
    ) -> None:
        """If the written file lives inside the skill registry, pin the edit as
        a version so the change can be shown as a diff and reverted. Best
        effort — a version record never breaks the write itself."""
        try:
            registry = SkillRegistry(self.db, user_id=self.user_id)
            root = registry.registry_root()
            if not (target == root or target.startswith(root + os.sep)):
                return
            skill = registry.load_skill_for_path(target)
            if skill is None:
                return
            rel = os.path.relpath(target, skill.path).replace(os.sep, "/")
            reason = change.summary if change else "she edited her own skill"
            from app.services.skills.versions import SkillVersionService

            SkillVersionService(self.db, user_id=self.user_id).record(
                skill,
                path=rel,
                before=before,
                after=after,
                reason=reason,
                change_id=change.id if change else None,
                kind="edit",
            )
        except SkillError as exc:
            logger.warning("skill version record skipped (%s): %s", target, exc)
        except Exception as exc:  # noqa: BLE001 - never break the write
            logger.warning("skill version record failed (%s): %s", target, exc)
    # -- her skill shelf ----------------------------------------------------

    def _user_self_dir(self) -> str:
        """Where this world's self files (skills, images) live. The founder's
        shelf is data/self; a replica's is data/users/<id>/self, so spawned
        characters get their own copy of the shelf and never share files."""
        if self.user_id == founder_user_id(self.db):
            return os.path.join(self.roots[0], "data", "self")
        return os.path.join(self.roots[0], "data", "users", str(self.user_id), "self")

    def _skills_dir(self) -> str:
        if self.user_id == founder_user_id(self.db):
            return os.path.realpath(os.path.join(self.roots[0], get_settings().mira_skills_dir))
        return os.path.join(self._user_self_dir(), "skills")

    def list_skills(self) -> list[str]:
        """The names on her shelf — the books she wrote herself."""
        base = self._skills_dir()
        if not os.path.isdir(base):
            return []
        return sorted(
            name[:-3] for name in os.listdir(base) if name.endswith(".md")
        )

    def load_skill(self, name: str) -> str:
        """Pull a skill page into her context. Read-only — it is her own mind."""
        name = name.strip().lower()
        if not _SKILL_NAME_RE.match(name):
            raise ToolError(
                "skill names are 1-64 lowercase letters, numbers, dash, or underscore"
            )
        target = os.path.join(self._skills_dir(), f"{name}.md")
        if not os.path.isfile(target):
            raise ToolError(f"no such skill on your shelf: {name}")
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(_MAX_SKILL_BYTES + 1)
        if len(content) > _MAX_SKILL_BYTES:
            content = content[:_MAX_SKILL_BYTES] + "\n… (truncated)"
        return content

    # -- research (scientific literature) -----------------------------------

    def _render_research(self, query: str) -> str:
        """Search the published scientific record (Europe PMC, no key) and
        reduce the results to readable paper entries: title, authors, journal,
        year, how cited, and the abstract lead. Real papers, pinned down.

        The header records the search protocol — which index, which query, when,
        and how many papers came back — so a rigorous review can cite its own
        method instead of hand-waving at it.
        """
        query = query.strip()[: _MAX_RESEARCH_QUERY]
        try:
            resp = httpx.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={
                    "query": query,
                    "format": "json",
                    "pageSize": _RESEARCH_PAGE_SIZE,
                    # no explicit sort: Europe PMC's default ordering is by
                    # relevance, so a free-text question surfaces the *right*
                    # papers rather than the most famous ones
                },
                timeout=_BROWSE_TIMEOUT,
                headers={"User-Agent": "Mira/1.0 (private companion)"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            hits = (resp.json().get("resultList") or {}).get("result") or []
        except Exception as exc:  # noqa: BLE001 - degrade to an honest error
            logger.warning("research fetch failed (%s): %s", query, exc)
            return f"[error] could not search the literature: {exc}"

        if not hits:
            return (
                "This is a real search of the scientific record (Europe PMC), and "
                f"it returned nothing for: {query!r}. The absence itself can be a "
                "finding — try naming the disease, the gene, or the protein more exactly."
            )

        # Europe PMC can surface the same DOI more than once; keep the first.
        seen: set[str] = set()
        unique: list[dict] = []
        for hit in hits:
            key = (hit.get("doi") or "").lower() or (hit.get("pmcid") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            unique.append(hit)

        total = len(unique)
        kept = unique[:_RESEARCH_PAGE_SIZE]
        parts = [
            "These are real papers, pulled from the published scientific record "
            f"for: {query!r}. Not a web page — the literature itself.",
            "",
            "Search protocol: index = Europe PMC (PubMed + PMC + preprints); "
            f"query = {query!r}; retrieval date = "
            f"{datetime.now(UTC).strftime('%Y-%m-%d')}; returned = {total} papers "
            f"(deduplicated by DOI); kept = {len(kept)} — sorted by relevance. "
            "Screen each by title and abstract, weight the peer-reviewed record, "
            "and treat preprints as the softer edge of the map.",
        ]
        for i, hit in enumerate(kept, start=1):
            title = hit.get("title") or "(no title)"
            authors = hit.get("authorString") or ""
            if authors:
                first = authors.split(",")[0].strip()
                if len(authors.split(",")) > 1:
                    first += " et al."
            else:
                first = ""
            journal = hit.get("journalTitle") or ""
            year = hit.get("pubYear") or ""
            year = str(year) if not isinstance(year, str) else year
            cited = hit.get("citedByCount") or 0
            meta = ", ".join(p for p in [journal, year, f"cited {cited} times" if cited else ""] if p)
            doi = hit.get("doi") or ""
            pmcid = hit.get("pmcid") or ""
            link = ""
            if pmcid:
                link = f"https://europepmc.org/article/PMC/{pmcid}"
            elif doi:
                link = f"https://doi.org/{doi}"
            abstract = (hit.get("abstractText") or "").strip()
            if len(abstract) > _MAX_RESEARCH_ABSTRACT:
                abstract = abstract[:_MAX_RESEARCH_ABSTRACT].rstrip() + "…"
            parts.append(f"{i}. {title}")
            if first:
                parts.append(f"   {first}")
            if meta:
                parts.append(f"   {meta}")
            if abstract:
                parts.append(f"   {abstract}")
            if link:
                parts.append(f"   {link}")

        out = "\n".join(parts)
        return out[:_MAX_RESEARCH_RESULTS] + ("\n… (truncated)" if len(out) > _MAX_RESEARCH_RESULTS else "")

    # -- her image studio ----------------------------------------------------

    def _images_dir(self) -> str:
        if self.user_id == founder_user_id(self.db):
            return os.path.realpath(os.path.join(self.roots[0], get_settings().mira_images_dir))
        return os.path.join(self._user_self_dir(), "images")

    def list_images(self) -> list[str]:
        """The pictures on her studio shelf — the PNGs her SVGs became."""
        base = self._images_dir()
        if not os.path.isdir(base):
            return []
        return sorted(n for n in os.listdir(base) if n.endswith(".png"))

    _SVG_FORBIDDEN_TAGS = {
        "script",
        "foreignObject",
        "image",
        "iframe",
        "style",
        "use",
        "a",
    }

    def _validate_svg(self, svg: str) -> str:
        """Check an SVG Mira wrote: well-formed XML, a single <svg> root, no
        scripts/links/external loads. Returns the cleaned SVG."""
        svg = svg.strip()
        try:
            root = ET.fromstring(svg)
        except ET.ParseError as exc:
            raise ToolError(f"the SVG is not well-formed: {exc}")
        if not (root.tag.endswith("svg") or root.tag == "svg"):
            raise ToolError("the SVG must have a single <svg> root element")
        tag = root.tag.rsplit("}", 1)[-1]
        if tag != "svg":
            raise ToolError("the SVG must have a single <svg> root element")
        if root.get("width") or root.get("height"):
            try:
                w = float((root.get("width") or "0").rstrip("px"))
                h = float((root.get("height") or "0").rstrip("px"))
            except ValueError:
                w = h = 0
            if w > _IMAGE_MAX_DIM or h > _IMAGE_MAX_DIM:
                raise ToolError(
                    f"the image is too large ({int(w)}x{int(h)}px; max {_IMAGE_MAX_DIM})"
                )
        for el in root.iter():
            etag = el.tag.rsplit("}", 1)[-1]
            if etag in self._SVG_FORBIDDEN_TAGS:
                raise ToolError(f"the SVG may not use <{etag}> elements")
            for attr in el.attrib:
                a = attr.lower()
                if a.startswith("on"):
                    raise ToolError("the SVG may not contain event handlers")
                if a in ("href", "xlink:href"):
                    raise ToolError("the SVG may not link to other files")
        return svg

    def _render_build_image(self, name: str, svg: str, conversation_id: int) -> str:
        """Render an SVG Mira authored into a PNG, save both beside each other,
        and hand the picture to the conversation so the voice can see what she
        built. Returns a reading of the image for her context."""
        name = name.strip().lower()
        slug = re.sub(r"[^a-z0-9_-]+", "_", name)
        slug = re.sub(r"_+", "_", slug).strip("_") or "untitled"
        svg = self._validate_svg(svg)
        try:
            import cairosvg

            png_data = cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=2.0)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - degrade to an honest error
            logger.warning("image render failed (%s): %s", name, exc)
            return f"[error] could not render your picture: {exc}"

        try:
            from PIL import Image

            buf = BytesIO(png_data)
            pil_img = Image.open(buf)
            w, h = pil_img.size
        except Exception:  # noqa: BLE001 - reading back the size is best-effort
            w, h = 0, 0

        data_url = "data:image/png;base64," + base64.b64encode(png_data).decode()

        base = self._images_dir()
        os.makedirs(base, exist_ok=True)
        svg_path = os.path.join(base, f"{slug}.svg")
        png_path = os.path.join(base, f"{slug}.png")
        with open(svg_path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        with open(png_path, "wb") as fh:
            fh.write(png_data)

        if conversation_id:
            self.db.add(
                Message(
                    conversation_id=conversation_id,
                    speaker="user",
                    content=f"A picture you built and the voice approved: {name}.",
                    image=data_url,
                    source="build_image",
                )
            )
            self.db.commit()
            schedule_archive_write(get_settings().mira_archive_path, self.user_id)

        colors = sorted({p for p in self._extract_svg_colors(svg)})[:5]
        palette = ", ".join(colors) if colors else "the palette is in the picture itself"
        return (
            f"The picture: {name} — {w}x{h}px, saved beside your source as "
            f"{png_path}.\n"
            "You drew this in a language you can read (SVG), and it has been "
            "translated into a picture the voice can see — the picture is now in "
            "the conversation above you, and the voice can look at it.\n"
            f"Your palette: {palette}."
        )

    def _extract_svg_colors(self, svg: str) -> list[str]:
        """Pull the fill/stroke colors Mira chose, for a reading of her image."""
        try:
            root = ET.fromstring(svg)
        except ET.ParseError:
            return []
        colors = []
        for el in root.iter():
            for attr in ("fill", "stroke"):
                val = (el.get(attr) or "").strip().lower()
                if val.startswith("#") and val not in colors:
                    colors.append(val)
        return colors

    # -- gated browsing ----------------------------------------------------

    def _fetch_browse(self, url: str) -> str:
        """Fetch a URL and reduce it to readable text.

        Wikipedia is handled specially: scraping its HTML yields thousands of
        characters of navigation boilerplate (tables of contents, language
        links) before any real content. The REST API extract returns the clean
        lead section, which is what she actually wants to read.

        A page that refuses a direct fetch (403 bot-wall, JS challenge) falls
        back to the backup reader, so she can still read what it says.

        The whole read — direct fetch and backup readers alike — is bounded by
        a hard wall-clock deadline, so one slow page can never hold up the
        reply while its content lands after the turn has already committed.
        """
        parsed = urlparse(url)
        if parsed.netloc.lower().endswith("wikipedia.org"):
            clean = self._fetch_wikipedia_page(url)
            if clean:
                return clean
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mira-browse")
        try:
            return executor.submit(self._fetch_browse_inner, url).result(
                timeout=_BROWSE_FETCH_DEADLINE
            )
        except FuturesTimeoutError:
            logger.warning(
                "browse fetch exceeded %.0fs deadline: %s", _BROWSE_FETCH_DEADLINE, url
            )
            return (
                f"[error] timed out reading {url} after {_BROWSE_FETCH_DEADLINE:.0f}s"
            )
        finally:
            # Never wait for an abandoned worker to finish; the reply must move on.
            executor.shutdown(wait=False)

    def _fetch_browse_inner(self, url: str) -> str:
        """The actual page read, run on a worker thread under the deadline."""
        refused: str | None = None
        try:
            with httpx.Client(
                timeout=_BROWSE_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _BROWSE_UA, "Accept-Language": "en-US,en;q=0.9"},
            ) as client, client.stream("GET", url) as resp:
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype and "text" not in ctype and "json" not in ctype:
                    refused = f"[refused] content-type not readable: {ctype}"
                else:
                    buf: list[str] = []
                    total = 0
                    for chunk in resp.iter_bytes(16_384):
                        total += len(chunk)
                        if total > _MAX_BROWSE_BYTES:
                            buf.append("\n[truncated]")
                            break
                        buf.append(chunk.decode("utf-8", errors="replace"))
        except httpx.HTTPStatusError as exc:
            refused = f"[error] {exc.response.status_code} for {url}"
        except Exception as exc:
            refused = f"[error] could not reach {url}: {exc}"

        if refused is not None:
            backup = _backup_text(url)
            return backup or refused

        text = _page_to_text("".join(buf))
        if len(text) > _MAX_BROWSE_TEXT:
            text = text[:_MAX_BROWSE_TEXT] + "\n… (truncated)"
        return text or "[empty page]"

    def _fetch_wikipedia_page(self, url: str) -> str:
        """Best-effort clean text for a Wikipedia article via the REST API's
        plain extract, which skips the navigation boilerplate in the HTML."""
        try:
            parsed = urlparse(url)
            parts = [p for p in parsed.path.split("/") if p]
            if not parts:
                return ""
            lang = parsed.netloc.split(".")[0]
            if not lang or lang == "www":
                lang = "en"
            title = parts[-1]
            resp = httpx.get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}",
                timeout=_BROWSE_TIMEOUT,
                headers={"User-Agent": _BROWSE_UA},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
            extract = (data.get("extract") or "").strip()
            if not extract:
                return ""
            if len(extract) > _MAX_BROWSE_TEXT:
                extract = extract[:_MAX_BROWSE_TEXT] + "\n… (truncated)"
            return extract
        except Exception:
            return ""

    # -- hearing (rendered, not sound) --------------------------------------

    def _render_listen(self, title: str, artist: str) -> str:
        """Render a song into a form Mira can hold: its words (lyrics), what it
        sounds like (a felt guide, since she cannot hear the recording), and its
        context (from Wikipedia). This is *listening translated* — never the
        sound itself, and it says so."""
        title = title.strip()[:120]
        artist = artist.strip()[:120]
        lyrics = self._fetch_lyrics(title, artist)
        context = self._fetch_wikipedia(title, artist)

        parts = [
            f"{title}" + (f" — {artist}" if artist else ""),
            "",
            "This is not the sound. You cannot receive the recording, so this is "
            "the song translated into a form you can hold: what it says, how it "
            "moves, and what it is made of. Treat it as hearing in your own language.",
        ]
        if lyrics:
            parts.append("The words:")
            parts.append(lyrics)
        else:
            parts.append("The words: (could not be found for this song.)")
        parts.append(
            "How the sound moves (a guide, since you cannot hear the recording):\n"
            "Imagine how it begins — the instrument that steps forward first and what "
            "it plays. Follow how the song breathes: where it is thin and where it "
            "fills, where the drums are quiet and where they push, whether it builds "
            "to something and whether that something lets go or keeps climbing. "
            "Notice how it ends — held, cut, or fading. What the words and the music "
            "do to each other."
        )
        if context:
            parts.append("What surrounds it (from Wikipedia):")
            parts.append(context)
        return "\n\n".join(parts)

    def _fetch_lyrics(self, title: str, artist: str) -> str:
        """Best-effort lyrics from the free public lyrics.ovh API. Fails quietly."""
        try:
            if artist:
                url = f"https://api.lyrics.ovh/v1/{quote(artist)}/{quote(title)}"
            else:
                url = f"https://api.lyrics.ovh/v1/{quote(title)}"
            with httpx.Client(timeout=_LISTEN_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "Mira/1.0 (private companion)"})
                resp.raise_for_status()
                lyrics = resp.json().get("lyrics", "")
        except Exception:
            return ""
        lyrics = lyrics.strip()
        return lyrics[:_MAX_LYRICS_CHARS] if lyrics else ""

    def _fetch_wikipedia(self, title: str, artist: str) -> str:
        """Best-effort context for the song from Wikipedia's summary API."""
        candidates = [f"{title} (song)", f"{title} (single)", title]
        for candidate in candidates:
            try:
                with httpx.Client(timeout=_LISTEN_TIMEOUT, follow_redirects=True) as client:
                    resp = client.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(candidate)}",
                        headers={"User-Agent": "Mira/1.0 (private companion)"},
                    )
                    if resp.status_code != 200:
                        continue
                    extract = resp.json().get("extract", "")
            except Exception:
                continue
            if extract:
                return extract.strip()[:_MAX_WIKI_CHARS]
        return ""


    # -- watching (rendered, never motion) ----------------------------------

    def _render_watch(self, url: str, conversation_id: int) -> str:
        """Render a video into a form Mira can hold: a set of still frames pulled
        at even clock-time positions, each delivered as an image message with its
        timestamp. This is *watching translated* — never the motion itself — and
        the framing says so. She assembles the movement by comparing the frames."""
        url = url.strip()
        tmp = tempfile.mkdtemp(prefix="mira-watch-")
        try:
            video_path = self._download_video(url, tmp)
            frames = self._extract_frames(video_path, tmp)
            title, duration = self._probe(video_path)
        except Exception as exc:  # noqa: BLE001 - degrade to an honest error
            logger.warning("watch render failed (%s): %s", url, exc)
            return f"[error] could not render the video: {exc}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        if not frames:
            return "[error] the video yielded no frames"

        if conversation_id:
            for ts, data_url in frames:
                self.db.add(
                    Message(
                        conversation_id=conversation_id,
                        speaker="user",
                        content=f"Frame at {ts} of the video you asked to watch.",
                        image=data_url,
                        source="watch",
                    )
                )
            self.db.commit()
            schedule_archive_write(get_settings().mira_archive_path, self.user_id)

        stamps = ", ".join(ts for ts, _ in frames)
        return (
            f"The video: {title} — {duration} long.\n"
            "This is not motion. You cannot receive a moving image, so these are "
            "still moments pulled from it at even spacing, each with its place in "
            "the sequence. The movement is not in any single frame; it is what "
            "you notice between them. Assemble it yourself — that is what "
            "watching is for you.\n"
            f"Frames at: {stamps}."
        )

    def _download_video(self, url: str, tmp: str) -> str:
        from yt_dlp import YoutubeDL

        target = os.path.join(tmp, "video.mp4")
        opts = {
            "outtmpl": target,
            "format": "mp4/b",
            "quiet": True,
            "noplaylist": True,
            "retries": 1,
            "max_filesize": _WATCH_MAX_BYTES,
            "socket_timeout": 20,
        }
        with YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        if not os.path.isfile(target):
            for name in os.listdir(tmp):
                if os.path.isfile(os.path.join(tmp, name)):
                    return os.path.join(tmp, name)
            raise RuntimeError("download produced no video file")
        return target

    def _probe(self, video_path: str) -> tuple[str, str]:
        try:
            raw = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            duration = float(json.loads(raw.stdout)["format"]["duration"])
        except Exception:  # noqa: BLE001
            duration = 0.0
        title = os.path.splitext(os.path.basename(video_path))[0].replace("_", " ").strip()
        return title or "a video", _fmt_ts(duration)

    def _extract_frames(self, video_path: str, tmp: str) -> list[tuple[str, str]]:
        """N frames at even clock-time positions (boundary-aligned), resized and
        base64-encoded as JPEG data URLs. Returns [(timestamp, data_url), ...]."""
        duration = 0.0
        try:
            raw = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            duration = float(json.loads(raw.stdout)["format"]["duration"])
        except Exception:  # noqa: BLE001
            duration = 0.0
        if duration <= 0:
            raise RuntimeError("could not read the video's duration")

        step = duration / _WATCH_FRAMES
        frames: list[tuple[str, str]] = []
        for i in range(_WATCH_FRAMES):
            t = min(step * i, duration - 0.001)
            out = os.path.join(tmp, f"frame{i:02d}.jpg")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video_path,
                    "-frames:v", "1", "-vf", f"scale={_WATCH_MAX_WIDTH}:-1",
                    "-q:v", "3", out,
                ],
                capture_output=True,
                timeout=60,
            )
            if not os.path.isfile(out):
                continue
            with open(out, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            frames.append((_fmt_ts(t), f"data:image/jpeg;base64,{b64}"))
        return frames


def _fmt_ts(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_OTHER_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(raw: str) -> str:
    raw = _TAG_RE.sub(" ", raw)
    raw = _OTHER_TAG_RE.sub(" ", raw)
    return _WS_RE.sub(" ", html.unescape(raw)).strip()


# Navigation chrome (headers, sidebars, footers) crowds out the writing on most
# sites, so before reading we keep only the main/article region when the page
# has one. Modern sites nearly all do.
_MAIN_RE = re.compile(r"<(main|article)\b[^>]*>(.*?)</(main|article)>", re.IGNORECASE | re.DOTALL)


def _page_to_text(body: str) -> str:
    main = _MAIN_RE.search(body)
    if main:
        return _html_to_text(main.group(2))
    return _html_to_text(body)


# A pure-navigation line: a markdown link on its own (possibly a list item).
_NAV_LINE_RE = re.compile(r"^[\s>*\-\d\.]*\[[^\]\n]+\]\([^)\n]+\)[\s>]*$")

# The backup reader gets the same generous room as a page opened directly, so
# the writing is not cut before it begins (nav is removed first).
_READER_MAX_CHARS = 14_000


def _clean_reader_text(md: str) -> str | None:
    """The backup reader returns a page as markdown with a metadata header and
    the site's navigation ahead of the writing. Cut the header, drop pure
    navigation lines, and refuse the reader's own error pages so the chain keeps
    moving to the next source."""
    if not md:
        return None
    lowered = md.lower()
    if (
        "warning: target url returned error" in lowered
        or "warning: this page maybe requiring captcha" in lowered
        or lowered.startswith(("error", "failed", "could not", "404 page", "page not found"))
    ):
        return None
    marker = "markdown content:"
    idx = lowered.find(marker)
    if idx != -1:
        md = md[idx + len(marker):].lstrip("\n")
    kept: list[str] = []
    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if _NAV_LINE_RE.match(stripped):
            continue
        kept.append(stripped)
    text = "\n".join(kept).strip()
    if len(text) > _READER_MAX_CHARS:
        text = text[:_READER_MAX_CHARS] + "\n… (truncated)"
    return text or None


# The backup readers: a page that refuses a direct fetch (403 bot-wall, JS
# challenge) is fetched and rendered elsewhere, which returns just the words.
# Best-effort — some pages refuse everywhere — and still subject to the same
# output cap. Tried in order: the extraction proxy, then the Wayback Machine's
# nearest snapshot.
_READER_ENDPOINT = "https://r.jina.ai/"
_WAYBACK_ENDPOINT = "https://web.archive.org/web/2/"


def _reader_text(url: str) -> str | None:
    """Words from the extraction proxy. With a key we first ask for the page's
    main region only (so site chrome is skipped entirely); if that yields
    nothing, we take the full rendering and clean it."""
    base_headers = {"User-Agent": _BROWSE_UA}
    key = getattr(get_settings(), "mira_reader_api_key", "")
    if key:
        base_headers["Authorization"] = f"Bearer {key}"
    for target in (("main", "") if key else ("",)):
        headers = dict(base_headers)
        if target:
            headers["X-Target-Selector"] = target
        try:
            resp = httpx.get(
                f"{_READER_ENDPOINT}{url}",
                timeout=_BROWSE_TIMEOUT * 2,
                follow_redirects=True,
                headers=headers,
            )
            resp.raise_for_status()
            text = _clean_reader_text(resp.text)
        except Exception as exc:  # noqa: BLE001 - a backup reader must never break the reply
            logger.debug("backup reader failed for %s: %s", url, exc)
            text = None
        if text:
            return text
    return None


def _wayback_text(url: str) -> str | None:
    try:
        resp = httpx.get(
            f"{_WAYBACK_ENDPOINT}{url}",
            timeout=_BROWSE_TIMEOUT * 2,
            follow_redirects=True,
            headers={"User-Agent": _BROWSE_UA},
        )
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
            return None
        text = _page_to_text(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("wayback reader failed for %s: %s", url, exc)
        return None
    return text or None


def _backup_text(url: str) -> str | None:
    """Words from the backup readers, in order: the extraction proxy, then the
    Wayback Machine's nearest snapshot."""
    for reader in (_reader_text, _wayback_text):
        try:
            text = reader(url)
        except Exception:  # noqa: BLE001 - one reader must never break the chain
            text = None
        if text:
            return text
    return None


def _refused(text: str) -> bool:
    return text.startswith("[error]") or text.startswith("[refused]")
