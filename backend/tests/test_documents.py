import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services.documents import DocumentError, DocumentService


@pytest.fixture()
def env(tmp_path, monkeypatch):
    class S:
        self_edit_roots = str(tmp_path)

    monkeypatch.setattr("app.services.documents.service.get_settings", lambda: S())

    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db, tmp_path
    finally:
        db.close()


def _founder_id(db) -> int:
    user = User(name="voice", role="person")
    db.add(user)
    db.commit()
    # ensure_founder promotes the earliest user to founder role.
    return db.query(User).order_by(User.id.asc()).first().id


def test_create_list_get_round_trip(env) -> None:
    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    doc = svc.create("A letter to Mira", "Dear Mira,\n\nI found something.")
    assert doc["name"] == "a-letter-to-mira"
    assert doc["author"] == "founder"
    assert doc["content"].startswith("Dear Mira")

    listing = svc.list_documents()
    assert [d["name"] for d in listing] == ["a-letter-to-mira"]
    assert listing[0]["author"] == "founder"
    assert "Dear Mira" in listing[0]["preview"]

    again = svc.get_document("a-letter-to-mira")
    assert again["content"] == "Dear Mira,\n\nI found something."
    # The file really landed under data/documents/founder/.
    assert (root / "data" / "documents" / "founder" / "a-letter-to-mira.md").is_file()


def test_same_slug_stays_unique_across_folders(env) -> None:
    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    svc.create("rain", "first")
    second = svc.create("rain", "second")
    assert second["name"] == "rain-2"
    assert len(svc.list_documents()) == 2


def test_list_sees_her_documents_too(env) -> None:
    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    mira_dir = root / "data" / "documents" / "mira"
    mira_dir.mkdir(parents=True)
    (mira_dir / "what-i-noticed.md").write_text("The quiet of the evening.", encoding="utf-8")

    listing = svc.list_documents()
    assert any(d["name"] == "what-i-noticed" and d["author"] == "mira" for d in listing)
    assert svc.get_document("what-i-noticed")["author"] == "mira"


def test_create_mira_writes_into_her_own_folder(env) -> None:
    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    doc = svc.create_mira("Research: exercise", "# Research: exercise\n\nThe review.")
    assert doc["name"] == "research-exercise"
    assert doc["author"] == "mira"
    assert doc["content"].startswith("# Research: exercise")
    # The paper lands under data/documents/mira/, not the founder's folder.
    assert (root / "data" / "documents" / "mira" / "research-exercise.md").is_file()
    assert not (root / "data" / "documents" / "founder" / "research-exercise.md").exists()


def test_create_mira_never_shadows_a_founder_paper(env) -> None:
    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    svc.create("rain", "first")
    mira = svc.create_mira("rain", "the review")
    assert mira["name"] == "rain-2"
    assert mira["author"] == "mira"
    assert len(svc.list_documents()) == 2


def test_create_mira_rejects_empty_and_oversized(env) -> None:
    db, root = env
    svc = DocumentService(db, user_id=_founder_id(db))
    with pytest.raises(DocumentError):
        svc.create_mira("", "text")
    with pytest.raises(DocumentError):
        svc.create_mira("a title", "")
    with pytest.raises(DocumentError):
        svc.create_mira("a title", "x" * 200_001)



    db, root = env
    svc = DocumentService(db, user_id=_founder_id(db))
    with pytest.raises(DocumentError):
        svc.create("", "text")
    with pytest.raises(DocumentError):
        svc.create("a title", "")
    with pytest.raises(DocumentError):
        svc.create("a title", "x" * 200_001)


def test_get_and_delete_unknown_raise(env) -> None:
    db, root = env
    svc = DocumentService(db, user_id=_founder_id(db))
    with pytest.raises(DocumentError):
        svc.get_document("nothing-here")
    assert svc.delete("nothing-here") is False


def test_unsafe_names_are_refused(env) -> None:
    db, root = env
    svc = DocumentService(db, user_id=_founder_id(db))
    with pytest.raises(DocumentError):
        svc.get_document("../secret")
    with pytest.raises(DocumentError):
        svc.get_document("a/b.md")
    assert svc.delete("../secret") is False


def test_delete_removes_the_file(env) -> None:
    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    svc.create("rain", "first")
    assert svc.delete("rain") is True
    assert not (root / "data" / "documents" / "founder" / "rain.md").exists()
    assert svc.list_documents() == []


def test_replica_worlds_do_not_share(env) -> None:
    db, root = env
    founder = _founder_id(db)
    other = User(name="someone", role="person")
    db.add(other)
    db.commit()
    other_id = other.id
    assert other_id != founder

    DocumentService(db, user_id=founder).create("private", "mine")
    # A replica sees an empty folder and cannot read the founder's paper.
    assert DocumentService(db, user_id=other_id).list_documents() == []
    with pytest.raises(DocumentError):
        DocumentService(db, user_id=other_id).get_document("private")


def _minimal_pdf(text: str) -> bytes:
    """A valid one-page PDF carrying ``text``, built by hand (no PDF writer)."""
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    stream = (
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
    )
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate([catalog, pages, page, stream, font], start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n"
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += (
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def test_create_from_pdf_extracts_text(env) -> None:
    db, root = env
    svc = DocumentService(db, user_id=_founder_id(db))
    data = _minimal_pdf(
        "Amyloid is a protein that folds wrong and settles as fibrils in the "
        "heart and kidney. Congo red turns it apple-green under polarized light."
    )
    doc = svc.create_from_pdf("", "lightmeta_patent2.pdf", data)
    assert doc["author"] == "founder"
    assert doc["name"] == "lightmeta_patent2"
    assert "fibrils" in doc["content"]
    assert "Congo red" in doc["content"]
    assert "handed over as lightmeta_patent2.pdf" in doc["content"]


def test_create_from_pdf_refuses_garbage_and_blank(env) -> None:
    db, root = env
    svc = DocumentService(db, user_id=_founder_id(db))
    with pytest.raises(DocumentError):
        svc.create_from_pdf("t", "f.pdf", b"this is not a pdf at all")
    with pytest.raises(DocumentError):
        svc.create_from_pdf("t", "blank.pdf", _minimal_pdf(""))


def test_download_markdown_serves_the_paper(env) -> None:
    from app.api.routes.documents import download_document

    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    svc.create("A letter to Mira", "Dear Mira,\n\nI found something.")
    resp = download_document("a-letter-to-mira", "md", db, user_id)
    assert resp.status_code == 200
    assert resp.body.decode("utf-8") == "Dear Mira,\n\nI found something."
    assert 'attachment; filename="a-letter-to-mira.md"' in resp.headers["content-disposition"]


def test_download_docx_and_pdf_render(env) -> None:
    from app.api.routes.documents import download_document

    db, root = env
    user_id = _founder_id(db)
    svc = DocumentService(db, user_id=user_id)
    svc.create("The Bull Market", "# The Bull Market\n\nA **rise** in prices.")

    word = download_document("the-bull-market", "docx", db, user_id)
    assert word.status_code == 200
    assert word.body.startswith(b"PK")
    assert 'attachment; filename="the-bull-market.docx"' in word.headers["content-disposition"]

    pdf = download_document("the-bull-market", "pdf", db, user_id)
    assert pdf.status_code == 200
    assert pdf.body.startswith(b"%PDF")
    assert 'attachment; filename="the-bull-market.pdf"' in pdf.headers["content-disposition"]


def test_download_unknown_document_404(env) -> None:
    from fastapi import HTTPException

    from app.api.routes.documents import download_document

    db, root = env
    user_id = _founder_id(db)
    with pytest.raises(HTTPException) as exc:
        download_document("does-not-exist", "md", db, user_id)
    assert exc.value.status_code == 404
