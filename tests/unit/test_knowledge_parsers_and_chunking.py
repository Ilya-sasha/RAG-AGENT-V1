from pathlib import Path

import pytest
from pypdf import PdfReader

from agent_runtime.knowledge.chunking import StructureFirstChunkingStrategy
from agent_runtime.knowledge.parsers import parse_document


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def _write_text_pdf(path: Path, pages: list[list[str]]) -> None:
    objects: list[str] = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + index * 2} 0 R' for index in range(len(pages)))}] /Count {len(pages)} >>",
    ]

    for index, lines in enumerate(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        content_lines = ["BT", "/F1 18 Tf", "72 720 Td"]
        for line in lines:
            escaped = _escape_pdf_text(line)
            content_lines.append(f"({escaped}) Tj")
            content_lines.append("0 -24 Td")
        content_lines.append("ET")
        stream = "\n".join(content_lines) + "\n"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {3 + len(pages) * 2} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}endstream")

    font_id = 3 + len(pages) * 2
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = "%PDF-1.4\n"
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(pdf.encode("utf-8")))
        pdf += f"{object_id} 0 obj\n{body}\nendobj\n"

    startxref = len(pdf.encode("utf-8"))
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{startxref}\n%%EOF\n"
    path.write_bytes(pdf.encode("utf-8"))


def test_parse_document_supports_markdown_txt_and_pdf(tmp_path) -> None:
    markdown_path = tmp_path / "guide.md"
    markdown_path.write_text("# Intro\n\nAlpha section", encoding="utf-8")

    text_path = tmp_path / "notes.txt"
    text_path.write_text("First paragraph\n\nSecond paragraph", encoding="utf-8")

    pdf_path = tmp_path / "manual.pdf"
    _write_text_pdf(pdf_path, [["Hello PDF"]])
    assert len(PdfReader(str(pdf_path)).pages) == 1

    markdown_doc = parse_document(markdown_path)
    text_doc = parse_document(text_path)
    pdf_doc = parse_document(pdf_path)

    assert markdown_doc.file_type == "markdown"
    assert markdown_doc.text == "# Intro\n\nAlpha section"

    assert text_doc.file_type == "txt"
    assert text_doc.text == "First paragraph\n\nSecond paragraph"

    assert pdf_doc.file_type == "pdf"
    assert pdf_doc.text.strip() == "Hello PDF"
    assert pdf_doc.metadata["page_count"] == 1


def test_structure_first_chunking_keeps_heading_boundaries() -> None:
    strategy = StructureFirstChunkingStrategy(max_chars=80)

    chunks = strategy.split_text(
        relative_path="guide.md",
        file_type="markdown",
        text="# Intro\n\nAlpha section\n\n## Details\n\nBeta paragraph",
    )

    assert len(chunks) == 2
    assert chunks[0].text == "Alpha section"
    assert chunks[0].source_locator["heading_path"] == ["Intro"]
    assert chunks[1].text == "Beta paragraph"
    assert chunks[1].source_locator["heading_path"] == ["Intro", "Details"]


def test_structure_first_chunking_tracks_heading_without_blank_line() -> None:
    strategy = StructureFirstChunkingStrategy(max_chars=80)

    chunks = strategy.split_text(
        relative_path="guide.md",
        file_type="markdown",
        text="# Intro\nAlpha section",
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Alpha section"
    assert chunks[0].source_locator["heading_path"] == ["Intro"]


def test_pdf_chunking_keeps_same_page_for_multiple_paragraphs() -> None:
    strategy = StructureFirstChunkingStrategy(max_chars=80)

    chunks = strategy.split_text(
        relative_path="manual.pdf",
        file_type="pdf",
        text="First paragraph\n\nSecond paragraph",
    )

    assert [chunk.text for chunk in chunks] == ["First paragraph", "Second paragraph"]
    assert chunks[0].source_locator["page"] == 1
    assert chunks[1].source_locator["page"] == 1


def test_pdf_chunking_preserves_later_page_numbers() -> None:
    strategy = StructureFirstChunkingStrategy(max_chars=80)

    chunks = strategy.split_text(
        relative_path="manual.pdf",
        file_type="pdf",
        text="Page one paragraph\fPage two first paragraph\n\nPage two second paragraph",
    )

    assert [chunk.source_locator["page"] for chunk in chunks] == [1, 2, 2]
    assert [chunk.text for chunk in chunks] == [
        "Page one paragraph",
        "Page two first paragraph",
        "Page two second paragraph",
    ]


def test_parse_document_preserves_path_structure(tmp_path) -> None:
    nested_path = tmp_path / "docs" / "topic" / "readme.md"
    nested_path.parent.mkdir(parents=True)
    nested_path.write_text("# Topic", encoding="utf-8")

    document = parse_document(nested_path)

    assert document.relative_path.replace("\\", "/").endswith("docs/topic/readme.md")
    assert document.relative_path != "readme.md"


def test_structure_first_chunking_rejects_non_positive_max_chars() -> None:
    with pytest.raises(ValueError, match="max_chars"):
        StructureFirstChunkingStrategy(max_chars=0)

    with pytest.raises(ValueError, match="max_chars"):
        StructureFirstChunkingStrategy(max_chars=-1)


def test_structure_first_chunking_returns_empty_for_blank_text() -> None:
    strategy = StructureFirstChunkingStrategy(max_chars=80)

    assert strategy.split_text(relative_path="blank.txt", file_type="txt", text="   ") == []
