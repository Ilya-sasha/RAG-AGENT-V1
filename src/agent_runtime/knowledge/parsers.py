from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

PDF_PAGE_SEPARATOR = "\f"


@dataclass(slots=True)
class ParsedDocument:
    relative_path: str
    file_type: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    relative_path = path.as_posix()

    if suffix == ".md":
        return ParsedDocument(
            relative_path=relative_path,
            file_type="markdown",
            text=path.read_text(encoding="utf-8"),
        )
    if suffix == ".txt":
        return ParsedDocument(
            relative_path=relative_path,
            file_type="txt",
            text=path.read_text(encoding="utf-8"),
        )
    if suffix == ".pdf":
        text, metadata = _parse_pdf(path)
        return ParsedDocument(
            relative_path=relative_path,
            file_type="pdf",
            text=text,
            metadata=metadata,
        )

    raise ValueError(f"unsupported document type: {path.suffix}")


def _parse_pdf(path: Path) -> tuple[str, dict[str, object]]:
    reader = PdfReader(str(path))
    page_text = [(page.extract_text() or "").strip() for page in reader.pages]
    return PDF_PAGE_SEPARATOR.join(page_text), {"page_count": len(reader.pages)}
