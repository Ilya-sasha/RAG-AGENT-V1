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


@pytest.mark.asyncio
async def test_upsert_document_move_refreshes_both_kb_counts_and_clears_stale_chunks(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = KnowledgeRepository(session_factory)

    kb_a = KnowledgeBaseRecord(
        kb_id="kb-a",
        tenant_id="tenant-a",
        name="KB A",
        root_path=str(tmp_path / "kb-a"),
        status="registered",
        embedding_provider_id="local-default",
        index_provider_id="sqlite-local",
        chunking_strategy="structure-first",
    )
    kb_b = KnowledgeBaseRecord(
        kb_id="kb-b",
        tenant_id="tenant-a",
        name="KB B",
        root_path=str(tmp_path / "kb-b"),
        status="registered",
        embedding_provider_id="local-default",
        index_provider_id="sqlite-local",
        chunking_strategy="structure-first",
    )
    await repository.upsert_knowledge_base(kb_a)
    await repository.upsert_knowledge_base(kb_b)

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
                source_locator={"path": "guide.md", "heading_path": ["Intro"]},
                metadata={"embedding": [1.0, 0.0]},
            )
        ],
    )

    await repository.upsert_document(
        DocumentRecord(
            document_id="doc-a",
            kb_id="kb-b",
            tenant_id="tenant-a",
            relative_path="guide.md",
            content_hash="hash-2",
            file_type="markdown",
            parse_status="indexed",
        )
    )

    stored_kb_a = await repository.get_knowledge_base("kb-a")
    stored_kb_b = await repository.get_knowledge_base("kb-b")
    stored_kb_b_documents = await repository.list_documents("kb-b")
    stored_chunks = await repository.list_document_chunks("doc-a")
    searchable_kb_a_chunks = await repository.list_searchable_chunks("tenant-a", ["kb-a"])

    assert stored_kb_a is not None
    assert stored_kb_a.document_count == 0
    assert stored_kb_a.chunk_count == 0
    assert stored_kb_b is not None
    assert stored_kb_b.document_count == 1
    assert stored_kb_b.chunk_count == 0
    assert stored_kb_b_documents[0].kb_id == "kb-b"
    assert stored_chunks == []
    assert searchable_kb_a_chunks == []


@pytest.mark.asyncio
async def test_replace_document_chunks_rejects_mismatched_document_or_owner(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = KnowledgeRepository(session_factory)

    kb = KnowledgeBaseRecord(
        kb_id="kb-a",
        tenant_id="tenant-a",
        name="KB A",
        root_path=str(tmp_path / "kb-a"),
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

    with pytest.raises(ValueError, match="document_id"):
        await repository.replace_document_chunks(
            "doc-a",
            [
                ChunkRecord(
                    chunk_id="chunk-bad-doc",
                    document_id="doc-b",
                    kb_id="kb-a",
                    tenant_id="tenant-a",
                    chunk_index=0,
                    text="alpha section",
                    text_length=13,
                    token_count=2,
                    source_locator={"path": "guide.md"},
                    metadata={"embedding": [1.0, 0.0]},
                )
            ],
        )

    with pytest.raises(ValueError, match="kb_id"):
        await repository.replace_document_chunks(
            "doc-a",
            [
                ChunkRecord(
                    chunk_id="chunk-bad-kb",
                    document_id="doc-a",
                    kb_id="kb-b",
                    tenant_id="tenant-a",
                    chunk_index=0,
                    text="alpha section",
                    text_length=13,
                    token_count=2,
                    source_locator={"path": "guide.md"},
                    metadata={"embedding": [1.0, 0.0]},
                )
            ],
        )

    with pytest.raises(ValueError, match="tenant_id"):
        await repository.replace_document_chunks(
            "doc-a",
            [
                ChunkRecord(
                    chunk_id="chunk-bad-tenant",
                    document_id="doc-a",
                    kb_id="kb-a",
                    tenant_id="tenant-b",
                    chunk_index=0,
                    text="alpha section",
                    text_length=13,
                    token_count=2,
                    source_locator={"path": "guide.md"},
                    metadata={"embedding": [1.0, 0.0]},
                )
            ],
        )

    assert await repository.list_document_chunks("doc-a") == []
