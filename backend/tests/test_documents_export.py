"""Tests for the humanized downloads — Markdown, Word, and PDF from the same
paper on disk."""

from app.services.documents import export

PAPER = """# Research: The Bull Market

*by Mira · August 15, 2026 · web research*

A **bull market** is a *sustained rise* in prices, per
[Investopedia](https://www.investopedia.com/terms/b/bullmarket.asp).

## Key takeaways

*   A bull market is a rise of 20% or more.
*   Traders watch market breadth and sentiment.

## References

1. Someone et al. (2024). "A Paper". Nature. https://doi.org/10.1000/x
"""


def test_markdown_bytes_are_the_paper_itself() -> None:
    assert export.markdown_bytes(PAPER).decode("utf-8") == PAPER


def test_docx_bytes_make_a_word_file() -> None:
    out = export.docx_bytes(PAPER)
    assert out.startswith(b"PK")  # a .docx is a zip package


def test_pdf_bytes_make_a_pdf() -> None:
    out = export.pdf_bytes(PAPER)
    assert out.startswith(b"%PDF")


def test_split_paper_pulls_title_and_byline() -> None:
    title, byline, body = export._split_paper(PAPER)
    assert title == "Research: The Bull Market"
    assert byline == "by Mira · August 15, 2026 · web research"
    assert "A **bull market**" in body


def test_blocks_find_heading_list_and_para() -> None:
    _, _, body = export._split_paper(PAPER)
    blocks = export._blocks(body)
    kinds = [b["kind"] for b in blocks]
    assert "heading" in kinds
    assert "list" in kinds
    assert "para" in kinds


def test_inline_splits_bold_italic_and_link() -> None:
    segs = export._inline("A **bold** and *it* with [link](https://x.y)")
    kinds = [k for k, _ in segs]
    assert kinds == ["text", "bold", "text", "italic", "text", "link"]
    link = next(v for k, v in segs if k == "link")
    assert link == ("link", "https://x.y")