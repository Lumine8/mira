from app.services.conversation.manager import _IMAGE_RE, _RESEARCH_RE, _SKILL_RE
from app.services.tools.service import _IMAGE_NAME_RE, _SKILL_NAME_RE


def test_skill_name_rule() -> None:
    assert _SKILL_NAME_RE.match("immunology")
    assert _SKILL_NAME_RE.match("language_of_silence")
    assert _SKILL_NAME_RE.match("scientific-research2")
    assert not _SKILL_NAME_RE.match("Immunology")  # must be lowercase
    assert not _SKILL_NAME_RE.match("../escape")
    assert not _SKILL_NAME_RE.match("a" * 65)
    assert not _SKILL_NAME_RE.match("with spaces")


def test_skill_marker_extraction() -> None:
    raw = (
        "I want to remember this. [[skill|immunology|I need my own words on this]] "
        "and maybe [[skill|language_of_silence|to notice the quiet]]"
    )
    names = [m.group("name").strip() for m in _SKILL_RE.finditer(raw)]
    assert names == ["immunology", "language_of_silence"]


def test_research_marker_extraction() -> None:
    raw = "Let me look this up properly. [[research|HLA-DQ8 type 1 diabetes peptide presentation|I want the literature]]"
    matches = list(_RESEARCH_RE.finditer(raw))
    assert len(matches) == 1
    assert matches[0].group("query").strip() == "HLA-DQ8 type 1 diabetes peptide presentation"
    assert matches[0].group("reason").strip() == "I want the literature"


def test_image_name_rule() -> None:
    assert _IMAGE_NAME_RE.match("a_map_with_holes")
    assert _IMAGE_NAME_RE.match("the patchy self")
    assert _IMAGE_NAME_RE.match("mira's presence")
    assert not _IMAGE_NAME_RE.match("../escape")
    assert not _IMAGE_NAME_RE.match("With Caps")


def test_image_marker_extraction_with_pipes_in_svg() -> None:
    raw = (
        "I want to see it. "
        "[[image|a_map_with_holes|to see my patchiness as a picture|"
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
        '<rect width="400" height="300" fill="#1a2332"/>'
        '<circle cx="200" cy="150" r="80" fill="none" stroke="#6ea8c8" stroke-width="2"/>'
        "</svg>]]"
        " that is all."
    )
    matches = list(_IMAGE_RE.finditer(raw))
    assert len(matches) == 1
    m = matches[0]
    assert m.group("name").strip() == "a_map_with_holes"
    assert m.group("reason").strip() == "to see my patchiness as a picture"
    svg = m.group("svg").strip()
    assert svg.startswith("<svg")
    assert "fill=\"#1a2332\"" in svg


def test_svg_validation_rejects_script_and_links() -> None:
    from app.services.tools import ToolError
    from app.services.tools.service import ToolService

    ts = ToolService.__new__(ToolService)

    ts._validate_svg(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
        '<circle cx="100" cy="100" r="50" fill="blue"/></svg>'
    )

    try:
        ts._validate_svg(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        )
        raise AssertionError("script should be rejected")
    except ToolError:
        pass

    try:
        ts._validate_svg(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<image href="http://evil.example/x.png"/></svg>'
        )
        raise AssertionError("embedded image should be rejected")
    except ToolError:
        pass

    try:
        ts._validate_svg("not xml at all")
        raise AssertionError("malformed xml should be rejected")
    except ToolError:
        pass
