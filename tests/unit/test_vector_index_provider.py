import math
import builtins
import types

import pytest

from agent_runtime.domain.models import ChunkRecord, DocumentRecord, KnowledgeBaseRecord
from agent_runtime.knowledge.embedding import LocalEmbeddingProvider
from agent_runtime.knowledge.index import LocalPersistentVectorIndexProvider
from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.state.db import build_session_factory, init_db


class FakeEmbeddingProvider:
    def provider_id(self) -> str:
        return "fake-test"

    def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        return [self.embed_query(chunk) for chunk in chunks]

    def embed_query(self, query: str) -> list[float]:
        vector = [
            1.0 if "alpha" in query.lower() else 0.0,
            1.0 if "beta" in query.lower() else 0.0,
            1.0 if "gamma" in query.lower() else 0.0,
        ]
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0.0:
            return [0.0, 0.0, 1.0]
        return [value / magnitude for value in vector]


async def _build_repository(tmp_path) -> KnowledgeRepository:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    return KnowledgeRepository(session_factory)


async def _store_kb(repository: KnowledgeRepository, tmp_path, *, kb_id: str, tenant_id: str) -> None:
    await repository.upsert_knowledge_base(
        KnowledgeBaseRecord(
            kb_id=kb_id,
            tenant_id=tenant_id,
            name=f"KB {kb_id}",
            root_path=str(tmp_path / kb_id),
            status="registered",
            embedding_provider_id="local-default",
            index_provider_id="sqlite-local",
            chunking_strategy="structure-first",
        )
    )


async def _store_document_with_chunks(
    repository: KnowledgeRepository,
    provider: FakeEmbeddingProvider,
    *,
    tenant_id: str,
    kb_id: str,
    document_id: str,
    relative_path: str,
    chunk_specs: list[tuple[str, str]],
) -> None:
    await repository.upsert_document(
        DocumentRecord(
            document_id=document_id,
            kb_id=kb_id,
            tenant_id=tenant_id,
            relative_path=relative_path,
            content_hash=f"hash-{document_id}",
            file_type="markdown",
            parse_status="indexed",
        )
    )
    chunks = [
        ChunkRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            kb_id=kb_id,
            tenant_id=tenant_id,
            chunk_index=index,
            text=text,
            text_length=len(text),
            token_count=len(text.split()),
            source_locator={"path": relative_path, "ordinal": index},
        )
        for index, (chunk_id, text) in enumerate(chunk_specs)
    ]
    index_provider = LocalPersistentVectorIndexProvider(repository)
    await index_provider.upsert_chunks(chunks, provider.embed_documents([chunk.text for chunk in chunks]))


@pytest.mark.asyncio
async def test_local_index_provider_filters_by_tenant_and_kb(tmp_path) -> None:
    repository = await _build_repository(tmp_path)
    provider = FakeEmbeddingProvider()
    index_provider = LocalPersistentVectorIndexProvider(repository)

    await _store_kb(repository, tmp_path, kb_id="kb-a", tenant_id="tenant-a")
    await _store_kb(repository, tmp_path, kb_id="kb-b", tenant_id="tenant-a")
    await _store_kb(repository, tmp_path, kb_id="kb-c", tenant_id="tenant-b")

    await _store_document_with_chunks(
        repository,
        provider,
        tenant_id="tenant-a",
        kb_id="kb-a",
        document_id="doc-a",
        relative_path="a.md",
        chunk_specs=[
            ("chunk-a1", "alpha only"),
            ("chunk-a2", "alpha beta"),
        ],
    )
    await _store_document_with_chunks(
        repository,
        provider,
        tenant_id="tenant-a",
        kb_id="kb-b",
        document_id="doc-b",
        relative_path="b.md",
        chunk_specs=[("chunk-b1", "beta only")],
    )
    await _store_document_with_chunks(
        repository,
        provider,
        tenant_id="tenant-b",
        kb_id="kb-c",
        document_id="doc-c",
        relative_path="c.md",
        chunk_specs=[("chunk-c1", "alpha gamma")],
    )

    hits = await index_provider.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query_vector=provider.embed_query("alpha beta"),
        top_k=5,
    )
    stats = await index_provider.get_index_stats("kb-a")

    assert [hit.chunk_id for hit in hits] == ["chunk-a2", "chunk-a1"]
    assert all(hit.tenant_id == "tenant-a" for hit in hits)
    assert all(hit.kb_id == "kb-a" for hit in hits)
    assert all("embedding" not in hit.metadata for hit in hits)
    assert hits[0].score > hits[1].score
    assert stats == {"document_count": 1, "chunk_count": 2}


@pytest.mark.asyncio
async def test_local_index_provider_delete_document_removes_chunks(tmp_path) -> None:
    repository = await _build_repository(tmp_path)
    provider = FakeEmbeddingProvider()
    index_provider = LocalPersistentVectorIndexProvider(repository)

    await _store_kb(repository, tmp_path, kb_id="kb-a", tenant_id="tenant-a")
    await _store_document_with_chunks(
        repository,
        provider,
        tenant_id="tenant-a",
        kb_id="kb-a",
        document_id="doc-a",
        relative_path="a.md",
        chunk_specs=[("chunk-a1", "alpha only")],
    )

    before_delete = await index_provider.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query_vector=provider.embed_query("alpha"),
        top_k=5,
    )

    await index_provider.delete_document("doc-a")

    after_delete = await index_provider.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query_vector=provider.embed_query("alpha"),
        top_k=5,
    )
    stats = await index_provider.get_index_stats("kb-a")

    assert [hit.chunk_id for hit in before_delete] == ["chunk-a1"]
    assert after_delete == []
    assert stats == {"document_count": 0, "chunk_count": 0}


@pytest.mark.asyncio
async def test_local_index_provider_rejects_mixed_document_batch(tmp_path) -> None:
    repository = await _build_repository(tmp_path)
    provider = FakeEmbeddingProvider()
    index_provider = LocalPersistentVectorIndexProvider(repository)

    await _store_kb(repository, tmp_path, kb_id="kb-a", tenant_id="tenant-a")
    await repository.upsert_document(
        DocumentRecord(
            document_id="doc-a",
            kb_id="kb-a",
            tenant_id="tenant-a",
            relative_path="a.md",
            content_hash="hash-doc-a",
            file_type="markdown",
            parse_status="indexed",
        )
    )
    await repository.upsert_document(
        DocumentRecord(
            document_id="doc-b",
            kb_id="kb-a",
            tenant_id="tenant-a",
            relative_path="b.md",
            content_hash="hash-doc-b",
            file_type="markdown",
            parse_status="indexed",
        )
    )

    chunks = [
        ChunkRecord(
            chunk_id="chunk-a1",
            document_id="doc-a",
            kb_id="kb-a",
            tenant_id="tenant-a",
            chunk_index=0,
            text="alpha only",
            text_length=10,
            token_count=2,
            source_locator={"path": "a.md", "ordinal": 0},
        ),
        ChunkRecord(
            chunk_id="chunk-b1",
            document_id="doc-b",
            kb_id="kb-a",
            tenant_id="tenant-a",
            chunk_index=0,
            text="beta only",
            text_length=9,
            token_count=2,
            source_locator={"path": "b.md", "ordinal": 0},
        ),
    ]

    with pytest.raises(ValueError, match="same document_id"):
        await index_provider.upsert_chunks(chunks, provider.embed_documents([chunk.text for chunk in chunks]))

    assert await repository.list_document_chunks("doc-a") == []
    assert await repository.list_document_chunks("doc-b") == []


def test_local_embedding_provider_lazy_loads_and_normalizes(monkeypatch) -> None:
    fake_module = types.ModuleType("sentence_transformers")
    import_calls: list[str] = []
    constructed_models: list[str] = []

    class FakeSentenceTransformer:
        def __init__(self, model_path: str) -> None:
            self.model_path = model_path
            constructed_models.append(model_path)

        def encode(self, inputs, normalize_embeddings=False):
            assert self.model_path == "models/test"
            assert normalize_embeddings is False
            if isinstance(inputs, str):
                return [3.0, 4.0]
            return [[3.0, 4.0], [0.0, 5.0]]

    fake_module.SentenceTransformer = FakeSentenceTransformer
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers":
            import_calls.append(name)
            return fake_module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    provider = LocalEmbeddingProvider("models/test")

    assert import_calls == []
    assert constructed_models == []
    assert provider.provider_id() == "local-default"
    assert provider.embed_documents(["doc 1", "doc 2"]) == [[0.6, 0.8], [0.0, 1.0]]
    assert provider.embed_query("query") == [0.6, 0.8]
    assert import_calls == ["sentence_transformers"]
    assert constructed_models == ["models/test"]


def test_local_embedding_provider_raises_actionable_error_for_invalid_model_path(monkeypatch) -> None:
    fake_module = types.ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        def __init__(self, model_path: str) -> None:
            raise ValueError("Unrecognized model in models/invalid")

    fake_module.SentenceTransformer = FakeSentenceTransformer
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers":
            return fake_module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    provider = LocalEmbeddingProvider("models/invalid")

    with pytest.raises(RuntimeError, match="models/invalid"):
        provider.embed_query("query")
