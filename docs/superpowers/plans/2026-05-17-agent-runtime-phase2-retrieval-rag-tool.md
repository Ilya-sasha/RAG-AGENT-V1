# Agent Runtime Phase 2 Retrieval Gateway And RAG Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tenant-scoped local-document retrieval with a persistent local vector index, internal ingest/reindex APIs, and a governed `rag_search` runtime tool.

**Architecture:** Keep the current runtime core intact and add a same-repository layered extension. Persistence stays in the existing SQLite-backed state store, knowledge ingestion lives in a new `knowledge` layer, retrieval lives in a new `retrieval` layer, and agent access happens only through a registered `rag_search` tool executor.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy async + SQLite, Prometheus metrics, `pypdf`, `sentence-transformers`, pytest

---

## File Structure

### Create

- `src/agent_runtime/knowledge/__init__.py`
  Package marker for knowledge-ingestion modules.
- `src/agent_runtime/knowledge/repository.py`
  Tenant-scoped knowledge-base, document, and chunk persistence operations.
- `src/agent_runtime/knowledge/parsers.py`
  `Markdown`, `TXT`, and `PDF` file parsing into normalized document content.
- `src/agent_runtime/knowledge/chunking.py`
  Structure-first chunking and source-locator generation.
- `src/agent_runtime/knowledge/providers.py`
  `EmbeddingProvider` and `VectorIndexProvider` protocols plus search result helpers.
- `src/agent_runtime/knowledge/embedding.py`
  Local embedding provider that loads models from `C:\models\embedding_models`.
- `src/agent_runtime/knowledge/index.py`
  Local persistent vector index backed by the runtime SQLite database.
- `src/agent_runtime/knowledge/service.py`
  Knowledge-base registration, ingest, incremental update, and reindex orchestration.
- `src/agent_runtime/retrieval/__init__.py`
  Package marker for retrieval modules.
- `src/agent_runtime/retrieval/service.py`
  Retrieval query execution and structured response assembly.
- `src/agent_runtime/tools/rag_search.py`
  `rag_search` tool executor wired into the runtime tool registry.
- `src/agent_runtime/api/routes/knowledge_bases.py`
  Internal management API for knowledge-base create/list/status/ingest/reindex.
- `tests/unit/test_knowledge_repository.py`
  Round-trip tests for knowledge-base, document, and chunk persistence.
- `tests/unit/test_knowledge_parsers_and_chunking.py`
  Parser and structure-first chunking tests.
- `tests/unit/test_vector_index_provider.py`
  Local persistent vector-index behavior tests.
- `tests/unit/test_retrieval_service.py`
  Structured retrieval response and compiled-context tests.
- `tests/integration/test_knowledge_bases_api.py`
  Internal management API and incremental ingest flow tests.
- `tests/integration/test_rag_search_tool.py`
  Runtime tool-gateway integration tests for `rag_search`.

### Modify

- `pyproject.toml`
  Add the minimum dependencies required for local PDF parsing and local embedding execution.
- `src/agent_runtime/domain/models.py`
  Add knowledge-base, document, chunk, and retrieval response records.
- `src/agent_runtime/state/tables.py`
  Add ORM tables for knowledge bases, documents, and indexed chunks.
- `src/agent_runtime/api/schemas.py`
  Add internal API request and response models for knowledge-base operations.
- `src/agent_runtime/api/app.py`
  Instantiate knowledge and retrieval services, register `rag_search`, and include the new internal router.
- `src/agent_runtime/observability/metrics.py`
  Add ingest and retrieval metrics for the new subsystem.

## Task 1: Add Persistence Models For Knowledge Bases, Documents, And Indexed Chunks

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/agent_runtime/domain/models.py`
- Modify: `src/agent_runtime/state/tables.py`
- Create: `src/agent_runtime/knowledge/repository.py`
- Test: `tests/unit/test_knowledge_repository.py`

- [ ] **Step 1: Write the failing repository round-trip test**

```python
import pytest

from agent_runtime.domain.models import ChunkRecord, DocumentRecord, KnowledgeBaseRecord
from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.state.db import build_session_factory, init_db


@pytest.mark.asyncio
async def test_knowledge_repository_round_trips_kb_document_and_chunks(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = KnowledgeRepository(session_factory)

    kb = KnowledgeBaseRecord(
        kb_id="kb-a",
        tenant_id="tenant-a",
        name="Operations KB",
        root_path=str(tmp_path / "kb"),
        status="registered",
        embedding_provider_id="local-default",
        index_provider_id="sqlite-local",
        chunking_strategy="structure-first",
    )
    await repository.upsert_knowledge_base(kb)

    document = DocumentRecord(
        document_id="doc-a",
        kb_id="kb-a",
        tenant_id="tenant-a",
        relative_path="guide.md",
        content_hash="hash-1",
        file_type="markdown",
        parse_status="indexed",
    )
    await repository.upsert_document(document)

    chunk = ChunkRecord(
        chunk_id="chunk-a",
        document_id="doc-a",
        kb_id="kb-a",
        tenant_id="tenant-a",
        chunk_index=0,
        text="alpha section",
        text_length=13,
        token_count=2,
        source_locator={"path": "guide.md", "heading_path": ["Intro"]},
        metadata={"embedding": [1.0, 0.0]},
    )
    await repository.replace_document_chunks("doc-a", [chunk])

    stored_kb = await repository.get_knowledge_base("kb-a")
    stored_documents = await repository.list_documents("kb-a")
    stored_chunks = await repository.list_document_chunks("doc-a")

    assert stored_kb is not None
    assert stored_kb.name == "Operations KB"
    assert stored_documents[0].relative_path == "guide.md"
    assert stored_chunks[0].source_locator["heading_path"] == ["Intro"]
```

- [ ] **Step 2: Run the focused repository test to verify it fails**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_knowledge_repository.py -v`
Expected: FAIL with import or attribute errors for `KnowledgeBaseRecord` or `KnowledgeRepository`

- [ ] **Step 3: Add the new dependency entries and persistence code**

```toml
[project]
dependencies = [
  "fastapi>=0.115.0,<1.0.0",
  "uvicorn>=0.30.0,<1.0.0",
  "pydantic>=2.8.0,<3.0.0",
  "sqlalchemy>=2.0.36,<3.0.0",
  "aiosqlite>=0.20.0,<1.0.0",
  "httpx>=0.27.0,<1.0.0",
  "prometheus-client>=0.21.0,<1.0.0",
  "pypdf>=5.1.0,<6.0.0",
  "sentence-transformers>=3.2.0,<4.0.0",
]
```

```python
# src/agent_runtime/domain/models.py
class KnowledgeBaseRecord(BaseModel):
    kb_id: str
    tenant_id: str
    name: str
    root_path: str
    status: str
    embedding_provider_id: str
    index_provider_id: str
    chunking_strategy: str
    document_count: int = 0
    chunk_count: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentRecord(BaseModel):
    document_id: str = Field(default_factory=lambda: str(uuid4()))
    kb_id: str
    tenant_id: str
    relative_path: str
    content_hash: str
    file_type: str
    parse_status: str
    last_indexed_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkRecord(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid4()))
    document_id: str
    kb_id: str
    tenant_id: str
    chunk_index: int
    text: str
    text_length: int
    token_count: int
    source_locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
```

```python
# src/agent_runtime/state/tables.py
class KnowledgeBaseTable(Base):
    __tablename__ = "knowledge_bases"

    kb_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    root_path: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    embedding_provider_id: Mapped[str] = mapped_column(String(128))
    index_provider_id: Mapped[str] = mapped_column(String(128))
    chunking_strategy: Mapped[str] = mapped_column(String(128))
    document_count: Mapped[int]
    chunk_count: Mapped[int]
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class KnowledgeDocumentTable(Base):
    __tablename__ = "knowledge_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.kb_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    relative_path: Mapped[str] = mapped_column(Text())
    content_hash: Mapped[str] = mapped_column(String(128))
    file_type: Mapped[str] = mapped_column(String(32))
    parse_status: Mapped[str] = mapped_column(String(32), index=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)


class KnowledgeChunkTable(Base):
    __tablename__ = "knowledge_chunks"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.document_id"), index=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.kb_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    chunk_index: Mapped[int]
    text: Mapped[str] = mapped_column(Text())
    text_length: Mapped[int]
    token_count: Mapped[int]
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
```

```python
# src/agent_runtime/knowledge/repository.py
class KnowledgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_knowledge_base(self, record: KnowledgeBaseRecord) -> None:
        async with self._session_factory() as session:
            row = await session.get(KnowledgeBaseTable, record.kb_id)
            if row is None:
                session.add(
                    KnowledgeBaseTable(
                        kb_id=record.kb_id,
                        tenant_id=record.tenant_id,
                        name=record.name,
                        root_path=record.root_path,
                        status=record.status,
                        embedding_provider_id=record.embedding_provider_id,
                        index_provider_id=record.index_provider_id,
                        chunking_strategy=record.chunking_strategy,
                        document_count=record.document_count,
                        chunk_count=record.chunk_count,
                        last_error=record.last_error,
                        metadata_json=record.metadata,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
            else:
                row.name = record.name
                row.root_path = record.root_path
                row.status = record.status
                row.document_count = record.document_count
                row.chunk_count = record.chunk_count
                row.last_error = record.last_error
                row.metadata_json = record.metadata
                row.updated_at = utc_now()
            await session.commit()

    async def get_knowledge_base(self, kb_id: str) -> KnowledgeBaseRecord | None:
        async with self._session_factory() as session:
            row = await session.get(KnowledgeBaseTable, kb_id)
            if row is None:
                return None
            return KnowledgeBaseRecord(
                kb_id=row.kb_id,
                tenant_id=row.tenant_id,
                name=row.name,
                root_path=row.root_path,
                status=row.status,
                embedding_provider_id=row.embedding_provider_id,
                index_provider_id=row.index_provider_id,
                chunking_strategy=row.chunking_strategy,
                document_count=row.document_count,
                chunk_count=row.chunk_count,
                last_error=row.last_error,
                metadata=row.metadata_json,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def list_documents(self, kb_id: str) -> list[DocumentRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(KnowledgeDocumentTable)
                    .where(KnowledgeDocumentTable.kb_id == kb_id)
                    .order_by(KnowledgeDocumentTable.relative_path)
                )
            ).scalars()
            return [
                DocumentRecord(
                    document_id=row.document_id,
                    kb_id=row.kb_id,
                    tenant_id=row.tenant_id,
                    relative_path=row.relative_path,
                    content_hash=row.content_hash,
                    file_type=row.file_type,
                    parse_status=row.parse_status,
                    last_indexed_at=row.last_indexed_at,
                    error_message=row.error_message,
                    metadata=row.metadata_json,
                )
                for row in rows
            ]

    async def replace_document_chunks(self, document_id: str, chunks: list[ChunkRecord]) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(KnowledgeChunkTable).where(KnowledgeChunkTable.document_id == document_id))
            for chunk in chunks:
                session.add(
                    KnowledgeChunkTable(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        kb_id=chunk.kb_id,
                        tenant_id=chunk.tenant_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        text_length=chunk.text_length,
                        token_count=chunk.token_count,
                        source_locator=chunk.source_locator,
                        embedding=chunk.metadata["embedding"],
                        metadata_json=chunk.metadata,
                    )
                )
            await session.commit()
```

Implementation rules:

- store the vector in `KnowledgeChunkTable.embedding`
- mirror the vector into `ChunkRecord.metadata["embedding"]` only in test helpers if needed, not in API responses
- update `document_count` and `chunk_count` after chunk replacement
- keep `KnowledgeRepository` separate from `RuntimeRepository`

- [ ] **Step 4: Run the focused repository test again**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_knowledge_repository.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add pyproject.toml src/agent_runtime/domain/models.py src/agent_runtime/state/tables.py src/agent_runtime/knowledge/repository.py tests/unit/test_knowledge_repository.py
git commit -m "feat: add knowledge persistence models"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 2: Add Markdown, TXT, And PDF Parsing Plus Structure-First Chunking

**Files:**
- Create: `src/agent_runtime/knowledge/parsers.py`
- Create: `src/agent_runtime/knowledge/chunking.py`
- Test: `tests/unit/test_knowledge_parsers_and_chunking.py`

- [ ] **Step 1: Write the failing parser and chunking tests**

```python
from pathlib import Path

import pytest

from agent_runtime.knowledge.chunking import StructureFirstChunkingStrategy
from agent_runtime.knowledge.parsers import parse_document


def _write_minimal_pdf(path: Path) -> None:
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length 44>>stream\nBT /F1 18 Tf 72 180 Td (PDF fixture text) Tj ET\nendstream endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000241 00000 n \n0000000311 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n406\n%%EOF\n"
    )


def test_parse_document_supports_markdown_txt_and_pdf(tmp_path) -> None:
    markdown = tmp_path / "guide.md"
    markdown.write_text("# Intro\n\nAlpha section\n\n## Details\n\nBeta paragraph", encoding="utf-8")
    txt = tmp_path / "notes.txt"
    txt.write_text("line one\n\nline two", encoding="utf-8")
    pdf = tmp_path / "manual.pdf"
    _write_minimal_pdf(pdf)

    md_doc = parse_document(markdown)
    txt_doc = parse_document(txt)
    pdf_doc = parse_document(pdf)

    assert md_doc.file_type == "markdown"
    assert txt_doc.file_type == "txt"
    assert "PDF fixture text" in pdf_doc.text


def test_structure_first_chunking_keeps_heading_boundaries() -> None:
    strategy = StructureFirstChunkingStrategy(max_chars=80)
    chunks = strategy.split_text(
        relative_path="virtual.md",
        file_type="markdown",
        text="# Intro\n\nAlpha section\n\n## Details\n\nBeta paragraph",
    )

    assert len(chunks) == 2
    assert chunks[0].source_locator["heading_path"] == ["Intro"]
    assert chunks[1].source_locator["heading_path"] == ["Intro", "Details"]
```

- [ ] **Step 2: Run the parser and chunking tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_knowledge_parsers_and_chunking.py -v`
Expected: FAIL with missing `parse_document` or `StructureFirstChunkingStrategy`

- [ ] **Step 3: Implement parsing and structure-first chunking**

```python
# src/agent_runtime/knowledge/parsers.py
@dataclass(slots=True)
class ParsedDocument:
    relative_path: str
    file_type: str
    text: str
    metadata: dict[str, Any]


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return ParsedDocument(path.name, "markdown", path.read_text(encoding="utf-8"), {})
    if suffix == ".txt":
        return ParsedDocument(path.name, "txt", path.read_text(encoding="utf-8"), {})
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return ParsedDocument(path.name, "pdf", "\n\n".join(pages).strip(), {"page_count": len(reader.pages)})
    raise ValueError(f"unsupported file type: {path.suffix}")
```

```python
# src/agent_runtime/knowledge/chunking.py
@dataclass(slots=True)
class ChunkDraft:
    text: str
    chunk_index: int
    source_locator: dict[str, Any]


class StructureFirstChunkingStrategy:
    def __init__(self, *, max_chars: int = 1200) -> None:
        self._max_chars = max_chars

    def split_text(self, *, relative_path: str, file_type: str, text: str) -> list[ChunkDraft]:
        if file_type == "markdown":
            return self._split_markdown(relative_path=relative_path, text=text)
        if file_type == "pdf":
            return self._split_blocks(relative_path=relative_path, text=text, locator_key="page_number")
        return self._split_blocks(relative_path=relative_path, text=text, locator_key="paragraph_index")
```

Implementation rules:

- preserve empty-document safety by returning `[]` for blank text
- for `Markdown`, track heading stacks in `source_locator["heading_path"]`
- for `TXT`, split on double newlines first, then length fallback
- for `PDF`, split by extracted page blocks first, then length fallback

- [ ] **Step 4: Run the parser and chunking tests again**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_knowledge_parsers_and_chunking.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add src/agent_runtime/knowledge/parsers.py src/agent_runtime/knowledge/chunking.py tests/unit/test_knowledge_parsers_and_chunking.py
git commit -m "feat: add knowledge parsers and chunking"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 3: Add Provider Interfaces, Local Embedding, And Persistent Local Vector Search

**Files:**
- Create: `src/agent_runtime/knowledge/providers.py`
- Create: `src/agent_runtime/knowledge/embedding.py`
- Create: `src/agent_runtime/knowledge/index.py`
- Test: `tests/unit/test_vector_index_provider.py`

- [ ] **Step 1: Write the failing local vector-index tests**

```python
import pytest

from agent_runtime.domain.models import ChunkRecord
from agent_runtime.knowledge.index import LocalPersistentVectorIndexProvider
from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.state.db import build_session_factory, init_db


class DeterministicEmbeddingProvider:
    def provider_id(self) -> str:
        return "deterministic-test"

    async def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "alpha" in chunk.lower() else [0.0, 1.0] for chunk in chunks]

    async def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0] if "alpha" in query.lower() else [0.0, 1.0]


@pytest.mark.asyncio
async def test_local_index_provider_filters_by_tenant_and_kb(tmp_path) -> None:
    session_factory = build_session_factory(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
    await init_db(session_factory)
    repository = KnowledgeRepository(session_factory)
    provider = LocalPersistentVectorIndexProvider(repository)

    await repository.replace_document_chunks(
        "doc-a",
        [
            ChunkRecord(
                chunk_id="chunk-a",
                document_id="doc-a",
                kb_id="kb-a",
                tenant_id="tenant-a",
                chunk_index=0,
                text="alpha section",
                text_length=13,
                token_count=2,
                source_locator={"path": "guide.md"},
                metadata={},
            ),
            ChunkRecord(
                chunk_id="chunk-b",
                document_id="doc-a",
                kb_id="kb-b",
                tenant_id="tenant-a",
                chunk_index=0,
                text="beta section",
                text_length=12,
                token_count=2,
                source_locator={"path": "guide.md"},
                metadata={},
            ),
        ],
    )

    await provider.attach_embeddings(
        {
            "chunk-a": [1.0, 0.0],
            "chunk-b": [0.0, 1.0],
        }
    )

    hits = await provider.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query_vector=[1.0, 0.0],
        top_k=2,
    )

    assert [hit.chunk_id for hit in hits] == ["chunk-a"]
    assert hits[0].score == pytest.approx(1.0)
```

- [ ] **Step 2: Run the vector-index tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_vector_index_provider.py -v`
Expected: FAIL with missing provider classes

- [ ] **Step 3: Implement provider protocols, lazy local embedding loading, and cosine search**

```python
# src/agent_runtime/knowledge/providers.py
class EmbeddingProvider(Protocol):
    async def embed_documents(self, chunks: list[str]) -> list[list[float]]: ...
    async def embed_query(self, query: str) -> list[float]: ...
    def provider_id(self) -> str: ...


class VectorSearchHit(BaseModel):
    chunk_id: str
    document_id: str
    kb_id: str
    tenant_id: str
    score: float
    text: str
    source_locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorIndexProvider(Protocol):
    async def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: dict[str, list[float]]) -> None: ...
    async def delete_document(self, document_id: str) -> None: ...
    async def search(self, *, tenant_id: str, kb_ids: list[str], query_vector: list[float], top_k: int) -> list[VectorSearchHit]: ...
    async def get_index_stats(self, kb_id: str) -> dict[str, int]: ...
    def provider_id(self) -> str: ...
```

```python
# src/agent_runtime/knowledge/embedding.py
class LocalEmbeddingProvider:
    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._model = None

    def provider_id(self) -> str:
        return "local-default"

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_path)
        return self._model

    async def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        model = self._load_model()
        return [list(vector) for vector in model.encode(chunks, normalize_embeddings=True)]
```

```python
# src/agent_runtime/knowledge/index.py
class LocalPersistentVectorIndexProvider:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    def provider_id(self) -> str:
        return "sqlite-local"

    async def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: dict[str, list[float]]) -> None:
        enriched = []
        for chunk in chunks:
            payload = chunk.model_copy(deep=True)
            payload.metadata["embedding"] = embeddings[chunk.chunk_id]
            enriched.append(payload)
        await self._repository.replace_document_chunks(chunks[0].document_id, enriched)

    async def search(self, *, tenant_id: str, kb_ids: list[str], query_vector: list[float], top_k: int) -> list[VectorSearchHit]:
        chunks = await self._repository.list_searchable_chunks(tenant_id=tenant_id, kb_ids=kb_ids)
        scored = []
        for chunk in chunks:
            embedding = chunk.metadata["embedding"]
            score = _cosine_similarity(query_vector, embedding)
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            VectorSearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                kb_id=chunk.kb_id,
                tenant_id=chunk.tenant_id,
                score=score,
                text=chunk.text,
                source_locator=chunk.source_locator,
                metadata=chunk.metadata,
            )
            for score, chunk in scored[:top_k]
        ]
```

Implementation rules:

- keep the `sentence-transformers` import lazy so non-embedding tests do not fail at import time
- normalize vectors once at embedding time and use pure-Python cosine math at query time
- store the embedding only in persistence and internal retrieval models, not in API responses

- [ ] **Step 4: Run the vector-index tests again**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_vector_index_provider.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add src/agent_runtime/knowledge/providers.py src/agent_runtime/knowledge/embedding.py src/agent_runtime/knowledge/index.py tests/unit/test_vector_index_provider.py
git commit -m "feat: add local embedding and vector index providers"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 4: Add The Knowledge Service And Internal Management API

**Files:**
- Create: `src/agent_runtime/knowledge/service.py`
- Create: `src/agent_runtime/api/routes/knowledge_bases.py`
- Modify: `src/agent_runtime/api/schemas.py`
- Modify: `src/agent_runtime/api/app.py`
- Test: `tests/integration/test_knowledge_bases_api.py`

- [ ] **Step 1: Write the failing internal API integration test**

```python
import pytest

from agent_runtime.api.app import create_app
from tests.conftest import app_client_context


class DeterministicEmbeddingProvider:
    def provider_id(self) -> str:
        return "deterministic-test"

    async def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "alpha" in chunk.lower() else [0.0, 1.0] for chunk in chunks]

    async def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0] if "alpha" in query.lower() else [0.0, 1.0]


@pytest.mark.asyncio
async def test_internal_knowledge_base_ingest_updates_status_and_counts(tmp_path) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    (kb_root / "guide.md").write_text("# Intro\n\nAlpha paragraph", encoding="utf-8")
    (kb_root / "notes.txt").write_text("Beta note", encoding="utf-8")

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=DeterministicEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-a",
                "tenant_id": "tenant-a",
                "name": "Ops KB",
                "root_path": str(kb_root),
            },
        )
        list_response = await client.get("/internal/knowledge-bases")
        ingest_response = await client.post("/internal/knowledge-bases/kb-a/ingest")
        reindex_response = await client.post("/internal/knowledge-bases/kb-a/reindex")
        status_response = await client.get("/internal/knowledge-bases/kb-a/status")

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert list_response.json()[0]["kb_id"] == "kb-a"
    assert ingest_response.status_code == 202
    assert reindex_response.status_code == 202
    assert status_response.status_code == 200
    assert status_response.json()["document_count"] == 2
    assert status_response.json()["chunk_count"] >= 2
```

- [ ] **Step 2: Run the internal API test to verify it fails**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/integration/test_knowledge_bases_api.py -v`
Expected: FAIL with missing route or schema errors

- [ ] **Step 3: Implement the knowledge service, schemas, and internal routes**

```python
# src/agent_runtime/api/schemas.py
class KnowledgeBaseCreateRequest(BaseModel):
    kb_id: str
    tenant_id: str
    name: str
    root_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseResponse(BaseModel):
    kb_id: str
    tenant_id: str
    name: str
    root_path: str
    status: str
    document_count: int
    chunk_count: int
    last_error: str | None
```

```python
# src/agent_runtime/knowledge/service.py
class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        embedding_provider: EmbeddingProvider,
        index_provider: VectorIndexProvider,
        chunking_strategy: StructureFirstChunkingStrategy,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._index_provider = index_provider
        self._chunking_strategy = chunking_strategy

    async def register_knowledge_base(self, *, kb_id: str, tenant_id: str, name: str, root_path: str, metadata: dict[str, Any]) -> KnowledgeBaseRecord:
        record = KnowledgeBaseRecord(
            kb_id=kb_id,
            tenant_id=tenant_id,
            name=name,
            root_path=root_path,
            status="registered",
            embedding_provider_id=self._embedding_provider.provider_id(),
            index_provider_id=self._index_provider.provider_id(),
            chunking_strategy="structure-first",
            metadata=metadata,
        )
        await self._repository.upsert_knowledge_base(record)
        return record

    async def list_knowledge_bases(self) -> list[KnowledgeBaseRecord]:
        return await self._repository.list_knowledge_bases()

    async def ingest(self, kb_id: str) -> KnowledgeBaseRecord:
        record = await self.get_status(kb_id)
        scanned = self._list_supported_paths(record.root_path)
        existing_documents = {doc.relative_path: doc for doc in await self._repository.list_documents(kb_id)}
        for relative_path, existing in existing_documents.items():
            if relative_path not in scanned:
                await self._index_provider.delete_document(existing.document_id)
        for path in scanned.values():
            parsed = parse_document(path)
            digest = _hash_text(parsed.text)
            existing = existing_documents.get(parsed.relative_path)
            if existing is not None and existing.content_hash == digest:
                continue
            await self._upsert_document_and_chunks(record, parsed, digest)
        refreshed = await self.get_status(kb_id)
        return refreshed.model_copy(update={"status": "success"})

    async def reindex(self, kb_id: str) -> KnowledgeBaseRecord:
        for document in await self._repository.list_documents(kb_id):
            await self._index_provider.delete_document(document.document_id)
        return await self.ingest(kb_id)

    async def get_status(self, kb_id: str) -> KnowledgeBaseRecord:
        record = await self._repository.get_knowledge_base(kb_id)
        if record is None:
            raise RuntimeError(f"knowledge base not found: {kb_id}")
        return record
```

```python
# src/agent_runtime/api/routes/knowledge_bases.py
router = APIRouter(prefix="/internal/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(request: Request, payload: KnowledgeBaseCreateRequest) -> KnowledgeBaseResponse:
    record = await request.app.state.knowledge_service.register_knowledge_base(**payload.model_dump())
    return KnowledgeBaseResponse(**record.model_dump())


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(request: Request) -> list[KnowledgeBaseResponse]:
    records = await request.app.state.knowledge_service.list_knowledge_bases()
    return [KnowledgeBaseResponse(**record.model_dump()) for record in records]


@router.post("/{kb_id}/ingest", response_model=ActionAcceptedResponse, status_code=202)
async def ingest_knowledge_base(request: Request, kb_id: str) -> ActionAcceptedResponse:
    await request.app.state.knowledge_service.ingest(kb_id)
    return ActionAcceptedResponse(status="accepted")


@router.post("/{kb_id}/reindex", response_model=ActionAcceptedResponse, status_code=202)
async def reindex_knowledge_base(request: Request, kb_id: str) -> ActionAcceptedResponse:
    await request.app.state.knowledge_service.reindex(kb_id)
    return ActionAcceptedResponse(status="accepted")
```

```python
# src/agent_runtime/api/app.py
knowledge_repository = KnowledgeRepository(session_factory)
embedding_provider = embedding_provider or LocalEmbeddingProvider(r"C:\models\embedding_models")
index_provider = vector_index_provider or LocalPersistentVectorIndexProvider(knowledge_repository)
chunking_strategy = StructureFirstChunkingStrategy()
knowledge_service = KnowledgeService(
    knowledge_repository,
    embedding_provider=embedding_provider,
    index_provider=index_provider,
    chunking_strategy=chunking_strategy,
)
await repository.upsert_tool_definition(
    ToolDefinitionRecord(
        tool_name="rag_search",
        description="Searches tenant-scoped knowledge bases",
        input_schema={
            "type": "object",
            "properties": {
                "kb_ids": {"type": "array", "items": {"type": "string"}},
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "include_compiled_context": {"type": "boolean"},
            },
            "required": ["kb_ids", "query"],
        },
        requires_approval=False,
    )
)
app.state.knowledge_service = knowledge_service
app.include_router(knowledge_bases_router)
```

Place the `upsert_tool_definition(...)` call inside `ensure_initialized()` after `init_db(session_factory)` so the built-in tool definition is idempotently present before any run starts.

Implementation rules:

- `ingest` handles new, changed, and deleted files by comparing content hashes and file presence
- `reindex` clears existing document chunks for the `kb_id` before rebuilding
- unsupported file types update status as `partial_success` only if at least one supported file succeeds
- default `LocalEmbeddingProvider` path is `C:\models\embedding_models`, but `create_app()` must accept injection overrides for tests

- [ ] **Step 4: Run the internal API integration test again**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/integration/test_knowledge_bases_api.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add src/agent_runtime/knowledge/service.py src/agent_runtime/api/routes/knowledge_bases.py src/agent_runtime/api/schemas.py src/agent_runtime/api/app.py tests/integration/test_knowledge_bases_api.py
git commit -m "feat: add knowledge base management api"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 5: Add The Retrieval Service And Governed `rag_search` Tool

**Files:**
- Create: `src/agent_runtime/retrieval/service.py`
- Create: `src/agent_runtime/tools/rag_search.py`
- Modify: `src/agent_runtime/domain/models.py`
- Modify: `src/agent_runtime/api/app.py`
- Test: `tests/unit/test_retrieval_service.py`
- Test: `tests/integration/test_rag_search_tool.py`

- [ ] **Step 1: Write the failing retrieval unit test and tool integration test**

```python
import pytest

from agent_runtime.retrieval.service import RetrievalService
from agent_runtime.knowledge.providers import VectorSearchHit


class StubEmbeddingProvider:
    def provider_id(self) -> str:
        return "stub"

    async def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        raise AssertionError("not used in query test")

    async def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0]


class FakeIndexProvider:
    def provider_id(self) -> str:
        return "fake-index"

    async def upsert_chunks(self, chunks, embeddings) -> None:
        raise AssertionError("not used in query test")

    async def delete_document(self, document_id: str) -> None:
        raise AssertionError("not used in query test")

    async def search(self, *, tenant_id: str, kb_ids: list[str], query_vector: list[float], top_k: int):
        return [
            VectorSearchHit(
                chunk_id="chunk-a",
                document_id="doc-a",
                kb_id="kb-a",
                tenant_id=tenant_id,
                score=1.0,
                text="alpha section",
                source_locator={"path": "guide.md", "heading_path": ["Intro"]},
                metadata={},
            ),
            VectorSearchHit(
                chunk_id="chunk-b",
                document_id="doc-a",
                kb_id="kb-a",
                tenant_id=tenant_id,
                score=0.8,
                text="alpha appendix",
                source_locator={"path": "guide.md", "heading_path": ["Appendix"]},
                metadata={},
            ),
        ][:top_k]

    async def get_index_stats(self, kb_id: str) -> dict[str, int]:
        return {"document_count": 1, "chunk_count": 2}


@pytest.mark.asyncio
async def test_retrieval_service_returns_hits_and_compiled_context() -> None:
    service = RetrievalService(
        embedding_provider=StubEmbeddingProvider(),
        index_provider=FakeIndexProvider(),
    )

    response = await service.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query="alpha",
        top_k=2,
        include_compiled_context=True,
    )

    assert len(response.hits) == 2
    assert "alpha section" in response.compiled_context
    assert response.hits[0].source_locator["path"] == "guide.md"
```

```python
import asyncio

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.domain.models import TenantPolicyRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context


class DeterministicEmbeddingProvider:
    def provider_id(self) -> str:
        return "deterministic-test"

    async def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "alpha" in chunk.lower() else [0.0, 1.0] for chunk in chunks]

    async def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0] if "alpha" in query.lower() else [0.0, 1.0]


@pytest.mark.asyncio
async def test_run_can_call_rag_search_through_tool_gateway(tmp_path) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    (kb_root / "guide.md").write_text("# Intro\n\nAlpha section", encoding="utf-8")

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="query kb",
                        tool_name="rag_search",
                        tool_arguments={
                            "kb_ids": ["kb-a"],
                            "query": "alpha",
                            "top_k": 3,
                            "include_compiled_context": True,
                        },
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="retrieval complete",
                    ),
                ]
            }
        ),
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    await app.state.ensure_initialized()
    await app.state.knowledge_service.register_knowledge_base(
        kb_id="kb-a",
        tenant_id="tenant-a",
        name="Ops KB",
        root_path=str(kb_root),
        metadata={},
    )
    await app.state.knowledge_service.ingest("kb-a")
    await app.state.run_service._repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["rag_search"],
            approval_required_tools=[],
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post("/v1/runs", json={"tenant_id": "tenant-a", "objective": "search kb"})
        run_id = create_response.json()["run_id"]
        for _ in range(20):
            run_payload = (await client.get(f"/v1/runs/{run_id}")).json()
            if run_payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

    assert run_payload["status"] == "completed"
```

- [ ] **Step 2: Run the retrieval tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_retrieval_service.py tests/integration/test_rag_search_tool.py -v`
Expected: FAIL with missing retrieval classes or missing `rag_search` registration

- [ ] **Step 3: Implement the retrieval service, response records, and tool executor**

```python
# src/agent_runtime/domain/models.py
class RetrievalHitRecord(BaseModel):
    kb_id: str
    document_id: str
    chunk_id: str
    score: float
    text: str
    source_locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResponseRecord(BaseModel):
    hits: list[RetrievalHitRecord]
    compiled_context: str | None = None
    query_metadata: dict[str, Any] = Field(default_factory=dict)
```

```python
# src/agent_runtime/retrieval/service.py
class RetrievalService:
    def __init__(self, *, embedding_provider: EmbeddingProvider, index_provider: VectorIndexProvider) -> None:
        self._embedding_provider = embedding_provider
        self._index_provider = index_provider

    async def search(
        self,
        *,
        tenant_id: str,
        kb_ids: list[str],
        query: str,
        top_k: int,
        include_compiled_context: bool,
    ) -> RetrievalResponseRecord:
        query_vector = await self._embedding_provider.embed_query(query)
        hits = await self._index_provider.search(
            tenant_id=tenant_id,
            kb_ids=kb_ids,
            query_vector=query_vector,
            top_k=top_k,
        )
        compiled_context = "\n\n".join(hit.text for hit in hits) if include_compiled_context else None
        return RetrievalResponseRecord(
            hits=[RetrievalHitRecord(**hit.model_dump()) for hit in hits],
            compiled_context=compiled_context,
            query_metadata={"top_k": top_k, "kb_ids": kb_ids},
        )
```

```python
# src/agent_runtime/tools/rag_search.py
class RagSearchToolExecutor:
    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        response = await self._retrieval_service.search(
            tenant_id=request.tenant_id,
            kb_ids=request.arguments["kb_ids"],
            query=request.arguments["query"],
            top_k=request.arguments.get("top_k", 5),
            include_compiled_context=request.arguments.get("include_compiled_context", False),
        )
        return ToolExecutionResult(output=response.model_dump())
```

```python
# src/agent_runtime/api/app.py
retrieval_service = RetrievalService(
    embedding_provider=embedding_provider,
    index_provider=index_provider,
)
registry.register("rag_search", RagSearchToolExecutor(retrieval_service))
app.state.retrieval_service = retrieval_service
```

Implementation rules:

- `rag_search` must use the existing `ToolGateway`, not a direct model-side shortcut
- retrieval input accepts only `kb_ids`, never a single `kb_id` field
- response metadata must exclude raw embeddings

- [ ] **Step 4: Run the retrieval tests again**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_retrieval_service.py tests/integration/test_rag_search_tool.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add src/agent_runtime/retrieval/service.py src/agent_runtime/tools/rag_search.py src/agent_runtime/domain/models.py src/agent_runtime/api/app.py tests/unit/test_retrieval_service.py tests/integration/test_rag_search_tool.py
git commit -m "feat: add rag retrieval tool"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 6: Add Retrieval Metrics, Incremental-Update Coverage, And Final Verification

**Files:**
- Modify: `src/agent_runtime/observability/metrics.py`
- Modify: `src/agent_runtime/knowledge/service.py`
- Modify: `tests/integration/test_knowledge_bases_api.py`
- Modify: `tests/unit/test_observability.py`
- Modify: `docs/superpowers/plans/2026-05-17-agent-runtime-phase2-retrieval-rag-tool.md`

- [ ] **Step 1: Extend the failing tests for metrics and incremental ingest**

```python
import pytest

@pytest.mark.asyncio
async def test_incremental_ingest_handles_added_changed_and_deleted_files(tmp_path) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    file_path = kb_root / "guide.md"
    file_path.write_text("# Intro\n\nalpha", encoding="utf-8")

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    async with app_client_context(app) as client:
        await client.post(
            "/internal/knowledge-bases",
            json={"kb_id": "kb-a", "tenant_id": "tenant-a", "name": "Ops KB", "root_path": str(kb_root)},
        )
        await client.post("/internal/knowledge-bases/kb-a/ingest")

        file_path.write_text("# Intro\n\nalpha updated", encoding="utf-8")
        (kb_root / "second.txt").write_text("beta", encoding="utf-8")
        await client.post("/internal/knowledge-bases/kb-a/ingest")

        file_path.unlink()
        await client.post("/internal/knowledge-bases/kb-a/ingest")
        status_response = await client.get("/internal/knowledge-bases/kb-a/status")

    assert status_response.json()["document_count"] == 1
```

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_ingest_and_retrieval_series(api_client: AsyncClient) -> None:
    metrics_response = await api_client.get("/metrics")

    assert "knowledge_ingest_requests_total" in metrics_response.text
    assert "knowledge_retrieval_queries_total" in metrics_response.text
```

- [ ] **Step 2: Run the focused metrics and incremental tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/integration/test_knowledge_bases_api.py tests/unit/test_observability.py -v`
Expected: FAIL because the new metrics and incremental-update assertions are not implemented yet

- [ ] **Step 3: Implement the metrics hooks and finish incremental-update handling**

```python
# src/agent_runtime/observability/metrics.py
class MetricsSink(Protocol):
    def record_knowledge_ingest(self, *, status: str) -> None: ...
    def record_retrieval_query(self, *, status: str, duration_seconds: float) -> None: ...


class PrometheusMetricsSink:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._knowledge_ingest = Counter(
            "knowledge_ingest_requests_total",
            "Knowledge ingest requests",
            ["status"],
            registry=self._registry,
        )
        self._retrieval_queries = Counter(
            "knowledge_retrieval_queries_total",
            "Knowledge retrieval queries",
            ["status"],
            registry=self._registry,
        )
        self._retrieval_query_duration = Histogram(
            "knowledge_retrieval_query_duration_seconds",
            "Knowledge retrieval query duration",
            ["status"],
            registry=self._registry,
        )
```

```python
# src/agent_runtime/knowledge/service.py
async def ingest(self, kb_id: str) -> KnowledgeBaseRecord:
    existing_documents = {doc.relative_path: doc for doc in await self._repository.list_documents(kb_id)}
    current_paths = self._list_supported_paths(record.root_path)

    for relative_path, existing in existing_documents.items():
        if relative_path not in current_paths:
            await self._index_provider.delete_document(existing.document_id)

    for path in current_paths.values():
        parsed = parse_document(path)
        digest = _hash_text(parsed.text)
        existing = existing_documents.get(parsed.relative_path)
        if existing is not None and existing.content_hash == digest:
            continue
        await self._upsert_document_and_chunks(record, parsed, digest)
```

Implementation rules:

- count unsupported files separately from hard failures
- update metrics once per ingest request and once per retrieval query
- keep the metrics series names stable so the existing `/metrics` surface remains Prometheus-friendly

- [ ] **Step 4: Run the new focused tests and then the full suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/integration/test_knowledge_bases_api.py tests/unit/test_observability.py -v`
Expected: PASS

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS, with retrieval and knowledge tests included in the full suite

- [ ] **Step 5: Record completion status in the final response**

```markdown
Summarize:

- new internal API routes
- new knowledge and retrieval modules
- `rag_search` runtime integration result
- verification commands and results
- deferred items still intentionally excluded from v1: external vector DB, more file types, semantic chunking, reranking, tracing
```

- [ ] **Step 6: Checkpoint changes locally**

```bash
git add src/agent_runtime/observability/metrics.py src/agent_runtime/knowledge/service.py tests/integration/test_knowledge_bases_api.py tests/unit/test_observability.py docs/superpowers/plans/2026-05-17-agent-runtime-phase2-retrieval-rag-tool.md
git commit -m "feat: finalize retrieval gateway phase"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.
