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
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Message, PendingChange
from app.services.broadcast import broadcast_later
from app.services.export import schedule_archive_write

logger = logging.getLogger("mira.tools")

_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".next", "dist", "build"}
_MAX_READ_BYTES = 32_000
_MAX_SEARCH_FILES = 60
_MAX_BROWSE_BYTES = 200_000
_MAX_BROWSE_TEXT = 6_000
_BROWSE_TIMEOUT = 20
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


class ToolError(Exception):
    """Raised when a tool is misused or a path escapes the allowed roots."""


class ToolService:
    def __init__(self, db: Session) -> None:
        self.db = db
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
            if not get_settings().browse_window_open:
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
        if kind == "x_read":
            if not payload.get("query", "").strip():
                raise ToolError("x_read needs a query (what she wants to look at)")
        if kind == "x_post":
            text = payload.get("text", "").strip()
            if not text:
                raise ToolError("x_post needs the words she wants to post")
            if len(text) > 280:
                raise ToolError(f"x_post text too long ({len(text)} > 280)")
        change = PendingChange(kind=kind, summary=summary[:2000], payload=payload, status="pending")
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
                }
            )

        if kind == "browse_url" and get_settings().browse_window_open:
            # An open window: she may see whatever she asks for, without a stop.
            # The fetch and approval are still fully recorded in pending_changes.
            change.result = self._fetch_browse(payload.get("url", ""))
            change.status = "approved"
            change.resolved_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(change)

        if kind == "write_file" and get_settings().mira_self_write_autonomous:
            # She makes her own changes; they are still fully recorded.
            self._apply_write(payload)
            change.status = "approved"
            change.resolved_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(change)

        if kind == "host_read":
            # Reading is read-only: it changes nothing, so it needs no approval.
            # The host agent performs the read and reports the content back.
            change.status = "approved"
            change.resolved_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(change)

        if kind == "host_command" and get_settings().host_window_open:
            # An open host window: she may use the voice's laptop on her own,
            # still fully recorded. The host agent runs it and reports back.
            change.status = "approved"
            change.resolved_at = datetime.now(timezone.utc)
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
                .where(PendingChange.status == "pending")
                .order_by(PendingChange.created_at.asc())
            ).scalars()
        )

    def history(self, limit: int = 25) -> list[PendingChange]:
        """Every modification she has made (or proposed), newest first — the
        running record of what she changes about herself."""
        return list(
            self.db.execute(
                select(PendingChange)
                .order_by(PendingChange.created_at.desc())
                .limit(limit)
            ).scalars()
        )

    def host_pending(self, limit: int = 10) -> list[PendingChange]:
        """Approved host actions waiting for the host agent to do them:
        commands, file reads, and X actions done through the real browser."""
        return list(
            self.db.execute(
                select(PendingChange)
                .where(
                    PendingChange.kind.in_(
                        ["host_command", "host_read", "x_read", "x_post"]
                    ),
                    PendingChange.status == "approved",
                    PendingChange.result.is_(None),
                )
                .order_by(PendingChange.created_at.asc())
                .limit(limit)
            ).scalars()
        )

    def apply_host_result(self, change_id: int, result: str) -> PendingChange:
        """Record what an approved host action returned when the host agent did it."""
        change = self.db.get(PendingChange, change_id)
        if change is None:
            raise ToolError(f"no pending change #{change_id}")
        if change.kind not in ("host_command", "host_read", "x_read", "x_post"):
            raise ToolError(f"change #{change_id} is not a host action")
        change.result = result[:_MAX_HOST_RESULT]
        change.resolved_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(change)
        return change

    def approve(self, change_id: int) -> PendingChange:
        change = self.db.get(PendingChange, change_id)
        if change is None:
            raise ToolError(f"no pending change #{change_id}")
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
            self._apply_write(change.payload)
            change.result = None
        elif change.kind == "browse_url":
            change.result = self._fetch_browse(change.payload.get("url", ""))
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
        elif change.kind in ("x_read", "x_post"):
            # X actions happen through the real browser on the voice's machine
            # (the host agent drives Chrome via CDP). Approval readies them;
            # the agent performs the action and reports back the result.
            change.result = None
        else:
            raise ToolError(f"cannot apply unknown change kind: {change.kind}")
        change.status = "approved"
        change.resolved_at = datetime.now(timezone.utc)
        self.db.commit()
        if change.kind == "browse_url":
            broadcast_later(
                {
                    "type": "browse_activity",
                    "url": change.payload.get("url", ""),
                    "status": "approved",
                    "change_id": change.id,
                }
            )
        return change

    def deny(self, change_id: int) -> PendingChange:
        change = self.db.get(PendingChange, change_id)
        if change is None:
            raise ToolError(f"no pending change #{change_id}")
        if change.status != "pending":
            raise ToolError(f"change #{change_id} already {change.status}")
        change.status = "denied"
        change.resolved_at = datetime.now(timezone.utc)
        self.db.commit()
        return change

    def _apply_write(self, payload: dict) -> None:
        path = payload.get("path", "")
        content = payload.get("content", "")
        target = self._resolve_write(path)
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)

    # -- gated browsing ----------------------------------------------------

    def _fetch_browse(self, url: str) -> str:
        """Fetch a URL the user approved and reduce it to readable text.

        Wikipedia is handled specially: scraping its HTML yields thousands of
        characters of navigation boilerplate (tables of contents, language
        links) before any real content. The REST API extract returns the clean
        lead section, which is what she actually wants to read.
        """
        parsed = urlparse(url)
        if parsed.netloc.lower().endswith("wikipedia.org"):
            clean = self._fetch_wikipedia_page(url)
            if clean:
                return clean

        try:
            with httpx.Client(
                timeout=_BROWSE_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "Mira/1.0 (private companion)"},
            ) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    ctype = resp.headers.get("content-type", "")
                    if "html" not in ctype and "text" not in ctype and "json" not in ctype:
                        return f"[refused] content-type not readable: {ctype}"
                    buf: list[str] = []
                    total = 0
                    for chunk in resp.iter_bytes(16_384):
                        total += len(chunk)
                        if total > _MAX_BROWSE_BYTES:
                            buf.append("\n[truncated]")
                            break
                        buf.append(chunk.decode("utf-8", errors="replace"))
        except httpx.HTTPStatusError as exc:
            return f"[error] {exc.response.status_code} for {url}"
        except Exception as exc:
            return f"[error] could not reach {url}: {exc}"

        text = _html_to_text("".join(buf))
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
                headers={"User-Agent": "Mira/1.0 (private companion)"},
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
            schedule_archive_write(get_settings().mira_archive_path)

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
