"""The documents API — the folder of papers she and the founder share.

The founder uploads a document here (it lands in founder/), and the documents
she writes herself (via her ordinary selfedit write path) appear here too.
Reading is free; writing is the founder's action; deletion is explicit.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.documents import DocumentError, DocumentService, export
from app.services.identity import get_current_user_id

router = APIRouter(prefix="/mira/documents", tags=["mira"])

_DOWNLOAD_FORMATS: dict[str, tuple[str, str]] = {
    # format -> (media type, file extension)
    "md": ("text/markdown", "md"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "pdf": ("application/pdf", "pdf"),
}


class DocumentCreateIn(BaseModel):
    """A paper the founder hands to Mira. The title becomes the file name;
    the content is the paper itself."""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=400_000)


@router.get("")
def list_documents(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """Every document in both folders, newest first, skimmed."""
    return DocumentService(db, user_id=user_id).list_documents()


@router.post("", status_code=201)
def create_document(
    body: DocumentCreateIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Hand Mira a paper: saved under founder/ and visible to her file tools."""
    try:
        return DocumentService(db, user_id=user_id).create(body.title, body.content)
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pdf", status_code=201)
def create_document_pdf(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Hand Mira a PDF: its text is extracted and stored as a markdown paper
    in founder/, so she can read it with her ordinary file tools."""
    data = file.file.read(20 * 1024 * 1024 + 1)
    try:
        return DocumentService(db, user_id=user_id).create_from_pdf(
            title or "", file.filename or "document.pdf", data
        )
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{name}/download")
def download_document(
    name: str,
    format: str = Query("md", pattern="^(md|docx|pdf)$"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> Response:
    """A paper, humanized for download — as Markdown, Word, or PDF. The body is
    rendered from the same markdown Mira wrote, with its title, byline,
    headings, lists, and the references/sources she cited."""
    try:
        doc = DocumentService(db, user_id=user_id).get_document(name)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_type, extension = _DOWNLOAD_FORMATS[format]
    try:
        if format == "md":
            body = export.markdown_bytes(doc["content"])
        elif format == "docx":
            body = export.docx_bytes(doc["content"])
        else:
            body = export.pdf_bytes(doc["content"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"could not render {format}: {exc}") from exc
    filename = f"{doc['name']}.{extension}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{name}")
def get_document(
    name: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """One document, in full — either folder, founder or hers."""
    try:
        return DocumentService(db, user_id=user_id).get_document(name)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{name}")
def delete_document(
    name: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Remove a document from the shared folder."""
    service = DocumentService(db, user_id=user_id)
    if not service.delete(name):
        raise HTTPException(status_code=404, detail=f"no such document: {name!r}")
    return {"name": name, "deleted": True}