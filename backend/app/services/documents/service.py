"""Mira and the founder's documents — a folder of papers, in her own hands.

Documents are plain markdown files, scoped per world like her shelf. The
founder's uploads land in ``founder/``; the papers Mira writes herself (through
her ordinary ``[[selfedit|...]]`` write path) land in ``mira/``. Because they
are real files, she can read and edit them with her normal file tools, and the
founder can see, read, and delete them here. This service is a thin shell over
that folder; there is no separate store to drift out of sync.
"""

import os
import re
import unicodedata
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.identity import founder_user_id

# A founder upload is capped so an accidentally pasted novel never wedges the
# screen; her own writes are bounded by her ordinary write paths instead.
_MAX_DOCUMENT_BYTES = 200_000
_MAX_TITLE_CHARS = 200
_PREVIEW_CHARS = 200
_FOLDERS = ("founder", "mira")
_NON_SLUG = re.compile(r"[^a-z0-9._-]+")
# PDFs are compressed, so the raw file gets a much bigger allowance than the
# extracted text; the extracted text still honors _MAX_DOCUMENT_BYTES.
_MAX_PDF_BYTES = 20 * 1024 * 1024
# A PDF with less readable text than this is almost certainly scanned images.
_MIN_PDF_TEXT_CHARS = 120


class DocumentError(Exception):
    """Raised when a document name is dangerous or missing."""


def _slug(title: str) -> str:
    """Turn a title into a safe file name: ascii, lowercase, no separators."""
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _NON_SLUG.sub("-", text.lower()).strip(".-")
    return text[:_MAX_TITLE_CHARS]


class DocumentService:
    """Scoped to one world: the founder sees data/documents, a replica its
    own data/users/<id>/documents — same folder, never shared."""

    def __init__(self, db: Session, *, user_id: int) -> None:
        self.db = db
        self.user_id = user_id

    # -- paths -----------------------------------------------------------------

    def root(self) -> str:
        roots = [r.strip() for r in get_settings().self_edit_roots.split(",") if r.strip()]
        base = os.path.realpath(roots[0] if roots else os.getcwd())
        if self.user_id == founder_user_id(self.db):
            return os.path.join(base, "data", "documents")
        return os.path.join(base, "data", "users", str(self.user_id), "documents")

    def _folder(self, author: str) -> str:
        return os.path.join(self.root(), author if author in _FOLDERS else "mira")

    # -- listing ---------------------------------------------------------------

    def _modified(self, path: str) -> str:
        """mtime as an ISO string; on weird filesystems that report absurd
        times, fall back to the present instead of failing the whole shelf."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return datetime.now(UTC).isoformat()
        try:
            return datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return datetime.now(UTC).isoformat()

    def list_documents(self) -> list[dict]:
        """Every paper in both folders, newest first, with a short preview so
        the shelf can be skimmed without loading full documents."""
        out: list[dict] = []
        for folder in _FOLDERS:
            base = self._folder(folder)
            if not os.path.isdir(base):
                continue
            for name in sorted(os.listdir(base)):
                if not name.endswith(".md"):
                    continue
                path = os.path.join(base, name)
                try:
                    size = os.path.getsize(path)
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        preview = fh.read(_PREVIEW_CHARS + 1)
                except OSError:
                    continue
                if len(preview) > _PREVIEW_CHARS:
                    preview = preview[:_PREVIEW_CHARS].rstrip() + "…"
                out.append(
                    {
                        "name": name[:-3],
                        "author": folder,
                        "size": size,
                        "preview": preview.strip(),
                        "modified_at": self._modified(path),
                    }
                )
        out.sort(key=lambda d: d["modified_at"], reverse=True)
        return out

    # -- reading ---------------------------------------------------------------

    def _resolve(self, name: str) -> tuple[str, str]:
        """Return (author, absolute path) for a document name, or raise."""
        if _slug(name) != name or not name:
            raise DocumentError(f"no such document: {name!r}")
        for folder in _FOLDERS:
            path = os.path.join(self._folder(folder), f"{name}.md")
            if os.path.isfile(path):
                return folder, path
        raise DocumentError(f"no such document: {name!r}")

    def get_document(self, name: str) -> dict:
        author, path = self._resolve(name)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        return {
            "name": name,
            "author": author,
            "content": content,
            "modified_at": self._modified(path),
        }

    # -- writing (founder uploads) ---------------------------------------------

    def create(self, title: str, content: str) -> dict:
        """The founder hands Mira a paper: saved into founder/, named by slug,
        kept unique across the whole folder so her name always resolves."""
        title = (title or "").strip()
        content = (content or "").strip()
        if not title:
            raise DocumentError("a document needs a title")
        if not content:
            raise DocumentError("a document needs some text")
        if len(content.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
            raise DocumentError("document too large to hand over")
        name = _slug(title)
        if not name:
            raise DocumentError("document title makes an empty file name")
        base = self._folder("founder")
        os.makedirs(base, exist_ok=True)
        name = self._unique_name(name)
        path = os.path.join(base, f"{name}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return self.get_document(name)

    def _unique_name(self, base: str) -> str:
        seen = set()
        for folder in _FOLDERS:
            directory = self._folder(folder)
            if os.path.isdir(directory):
                seen.update(n[:-3] for n in os.listdir(directory) if n.endswith(".md"))
        name = base
        index = 2
        while name in seen:
            name = f"{base}-{index}"
            index += 1
        return name

    def create_mira(self, title: str, content: str) -> dict:
        """A document Mira writes herself — e.g. the finished review of a
        research run. Saved into mira/, named by slug and kept unique across
        the whole folder, so her name always resolves and her papers never
        silently overwrite the founder's (or each other's)."""
        title = (title or "").strip()
        content = (content or "").strip()
        if not title:
            raise DocumentError("a document needs a title")
        if not content:
            raise DocumentError("a document needs some text")
        if len(content.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
            raise DocumentError("document too large to hand over")
        name = _slug(title)
        if not name:
            raise DocumentError("document title makes an empty file name")
        base = self._folder("mira")
        os.makedirs(base, exist_ok=True)
        name = self._unique_name(name)
        path = os.path.join(base, f"{name}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return self.get_document(name)

    # -- PDF hand-off ----------------------------------------------------------

    def create_from_pdf(self, title: str, filename: str, data: bytes) -> dict:
        """A PDF the founder drops on the Papers screen: its text is extracted
        and stored as a plain markdown document she can read with her file
        tools. Scanned (image-only) PDFs have nothing to extract and are
        refused with a plain reason."""
        import io

        from pypdf import PdfReader

        if len(data) > _MAX_PDF_BYTES:
            raise DocumentError("that PDF is too large to hand over")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            pages: list[str] = []
            for page in reader.pages:
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:  # pragma: no cover - a corrupt page, skip it
                    text = ""
                if text:
                    pages.append(text)
        except Exception as exc:
            raise DocumentError("that file does not look like a readable PDF") from exc
        text = "\n\n".join(pages).strip()
        if len(text) < _MIN_PDF_TEXT_CHARS:
            raise DocumentError(
                "this PDF has no readable text — it may be scanned images"
            )

        title = (title or "").strip() or os.path.splitext(os.path.basename(filename))[0]
        header = f"# {title}\n\n(handed over as {filename})\n\n"
        budget = _MAX_DOCUMENT_BYTES - len(header.encode("utf-8"))
        content = _cap_utf8(text, max(budget, 1))
        return self.create(title, header + content)

    # -- deletion --------------------------------------------------------------

    def delete(self, name: str) -> bool:
        try:
            _, path = self._resolve(name)
        except DocumentError:
            return False
        os.remove(path)
        # Leave the parent folders in place — she may write there again.
        return True


def _cap_utf8(text: str, limit: int) -> str:
    """Truncate to a byte budget without slicing through a multibyte char."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    cut = raw[:limit].decode("utf-8", errors="ignore")
    return cut.rstrip() + "\n\n… (the paper continues past the folder limit)"