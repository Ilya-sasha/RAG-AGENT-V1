from __future__ import annotations

from dataclasses import dataclass
import re

from agent_runtime.knowledge.parsers import PDF_PAGE_SEPARATOR


@dataclass(slots=True)
class ChunkDraft:
    text: str
    chunk_index: int
    source_locator: dict[str, object]


class StructureFirstChunkingStrategy:
    def __init__(self, max_chars: int = 1200) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be greater than 0")
        self.max_chars = max_chars

    def split_text(self, relative_path: str, file_type: str, text: str) -> list[ChunkDraft]:
        if not text.strip():
            return []

        if file_type == "markdown":
            blocks = self._markdown_blocks(relative_path, text)
        elif file_type == "txt":
            blocks = self._plain_text_blocks(relative_path, text)
        elif file_type == "pdf":
            blocks = self._pdf_blocks(relative_path, text)
        else:
            raise ValueError(f"unsupported file type: {file_type}")

        chunks: list[ChunkDraft] = []
        for block_text, base_locator in blocks:
            parts = self._split_with_length_fallback(block_text)
            for local_index, part in enumerate(parts):
                locator = dict(base_locator)
                locator["local_order"] = local_index
                chunks.append(
                    ChunkDraft(
                        text=part,
                        chunk_index=len(chunks),
                        source_locator=locator,
                    )
                )
        return chunks

    def _markdown_blocks(self, relative_path: str, text: str) -> list[tuple[str, dict[str, object]]]:
        blocks: list[tuple[str, dict[str, object]]] = []
        heading_path: list[str] = []
        paragraph_order = 0
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            nonlocal paragraph_order
            if not paragraph_lines:
                return
            paragraph_order += 1
            block = "\n".join(paragraph_lines).strip()
            if not block:
                paragraph_lines.clear()
                return
            blocks.append(
                (
                    block,
                    {
                        "path": relative_path,
                        "heading_path": list(heading_path),
                        "paragraph_order": paragraph_order,
                    },
                )
            )
            paragraph_lines.clear()

        for raw_line in text.strip().splitlines():
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                continue
            heading_match = re.fullmatch(r"(#{1,6})\s+(.*)", line)
            if heading_match:
                flush_paragraph()
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_path = heading_path[: level - 1] + [title]
                continue
            paragraph_lines.append(line)
        flush_paragraph()
        return blocks

    def _plain_text_blocks(self, relative_path: str, text: str) -> list[tuple[str, dict[str, object]]]:
        blocks: list[tuple[str, dict[str, object]]] = []
        for paragraph_order, raw_block in enumerate(re.split(r"\n\s*\n", text.strip()), start=1):
            block = raw_block.strip()
            if not block:
                continue
            blocks.append((block, {"path": relative_path, "paragraph_order": paragraph_order}))
        return blocks

    def _pdf_blocks(self, relative_path: str, text: str) -> list[tuple[str, dict[str, object]]]:
        blocks: list[tuple[str, dict[str, object]]] = []
        for page_number, raw_page in enumerate(text.split(PDF_PAGE_SEPARATOR), start=1):
            page = raw_page.strip()
            if not page:
                continue
            for paragraph_order, raw_block in enumerate(re.split(r"\n\s*\n", page), start=1):
                block = raw_block.strip()
                if not block:
                    continue
                blocks.append(
                    (
                        block,
                        {"path": relative_path, "page": page_number, "paragraph_order": paragraph_order},
                    )
                )
        return blocks

    def _split_with_length_fallback(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text]

        parts: list[str] = []
        remaining = text.strip()
        while len(remaining) > self.max_chars:
            split_at = remaining.rfind(" ", 0, self.max_chars + 1)
            if split_at <= 0:
                split_at = self.max_chars
            parts.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            parts.append(remaining)
        return parts
