from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context


class FakeEmbeddingProvider:
    def provider_id(self) -> str:
        return "fake-embedding"

    def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in chunks]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    @staticmethod
    def _embed(text: str) -> list[float]:
        size = float(max(len(text), 1))
        checksum = float(sum(ord(char) for char in text) % 997)
        vowels = float(sum(1 for char in text.lower() if char in "aeiou"))
        return [size, checksum, vowels]


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self, failing_marker: str) -> None:
        self._failing_marker = failing_marker

    def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        for chunk in chunks:
            if self._failing_marker in chunk:
                raise RuntimeError(f"embedding failure for marker: {self._failing_marker}")
        return super().embed_documents(chunks)


@asynccontextmanager
async def knowledge_api_context(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
    *,
    embedding_provider: object | None = None,
) -> AsyncIterator[tuple[AsyncClient, object, Path]]:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=scripted_supervisor_client,
        embedding_provider=embedding_provider or FakeEmbeddingProvider(),
    )
    async with app_client_context(app) as client:
        yield client, app, kb_root


@pytest.mark.asyncio
async def test_knowledge_base_management_happy_path(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, kb_root):
        (kb_root / "guide.md").write_text("# Intro\n\nAlpha section\n\n## Details\n\nBeta paragraph", encoding="utf-8")
        (kb_root / "notes.txt").write_text("First paragraph\n\nSecond paragraph", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-happy",
                "tenant_id": "tenant-a",
                "name": "Happy Path KB",
                "root_path": str(kb_root),
                "metadata": {"team": "docs"},
            },
        )

        assert create_response.status_code == 201
        assert create_response.json() == {
            "kb_id": "kb-happy",
            "tenant_id": "tenant-a",
            "name": "Happy Path KB",
            "root_path": str(kb_root),
            "status": "registered",
            "document_count": 0,
            "chunk_count": 0,
            "last_error": None,
        }

        list_response = await client.get("/internal/knowledge-bases")
        assert list_response.status_code == 200
        assert list_response.json() == [create_response.json()]

        status_response = await client.get("/internal/knowledge-bases/kb-happy/status")
        assert status_response.status_code == 200
        assert status_response.json() == create_response.json()

        ingest_response = await client.post("/internal/knowledge-bases/kb-happy/ingest")
        assert ingest_response.status_code == 202
        assert ingest_response.json() == {"status": "accepted"}

        status_after_ingest = await client.get("/internal/knowledge-bases/kb-happy/status")
        assert status_after_ingest.status_code == 200
        assert status_after_ingest.json() == {
            "kb_id": "kb-happy",
            "tenant_id": "tenant-a",
            "name": "Happy Path KB",
            "root_path": str(kb_root),
            "status": "success",
            "document_count": 2,
            "chunk_count": 4,
            "last_error": None,
        }

        reindex_response = await client.post("/internal/knowledge-bases/kb-happy/reindex")
        assert reindex_response.status_code == 202
        assert reindex_response.json() == {"status": "accepted"}

        status_after_reindex = await client.get("/internal/knowledge-bases/kb-happy/status")
        assert status_after_reindex.status_code == 200
        assert status_after_reindex.json() == status_after_ingest.json()


@pytest.mark.asyncio
async def test_ingest_updates_document_and_chunk_counts(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, kb_root):
        (kb_root / "guide.md").write_text("# Intro\n\nAlpha section", encoding="utf-8")

        await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-counts",
                "tenant_id": "tenant-a",
                "name": "Counts KB",
                "root_path": str(kb_root),
            },
        )

        before_ingest = await client.get("/internal/knowledge-bases/kb-counts/status")
        assert before_ingest.json()["document_count"] == 0
        assert before_ingest.json()["chunk_count"] == 0

        first_ingest = await client.post("/internal/knowledge-bases/kb-counts/ingest")
        assert first_ingest.status_code == 202

        after_first_ingest = await client.get("/internal/knowledge-bases/kb-counts/status")
        assert after_first_ingest.json()["document_count"] == 1
        assert after_first_ingest.json()["chunk_count"] == 1

        (kb_root / "appendix.txt").write_text("One paragraph\n\nTwo paragraph", encoding="utf-8")
        second_ingest = await client.post("/internal/knowledge-bases/kb-counts/ingest")
        assert second_ingest.status_code == 202

        after_second_ingest = await client.get("/internal/knowledge-bases/kb-counts/status")
        assert after_second_ingest.json()["document_count"] == 2
        assert after_second_ingest.json()["chunk_count"] == 3


@pytest.mark.asyncio
async def test_incremental_ingest_handles_added_changed_and_deleted_files(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, app, kb_root):
        alpha_path = kb_root / "alpha.md"
        beta_path = kb_root / "beta.txt"
        gamma_path = kb_root / "gamma.txt"

        alpha_path.write_text("# Intro\n\nAlpha section", encoding="utf-8")
        beta_path.write_text("Beta paragraph", encoding="utf-8")

        await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-incremental",
                "tenant_id": "tenant-a",
                "name": "Incremental KB",
                "root_path": str(kb_root),
            },
        )
        await client.post("/internal/knowledge-bases/kb-incremental/ingest")

        repository = app.state.knowledge_repository
        initial_documents = await repository.list_documents("kb-incremental")
        initial_by_path = {document.relative_path: document for document in initial_documents}
        assert set(initial_by_path) == {"alpha.md", "beta.txt"}

        alpha_path.write_text(
            "# Intro\n\nAlpha section\n\n## Details\n\nBeta section",
            encoding="utf-8",
        )
        beta_path.unlink()
        gamma_path.write_text("Gamma first\n\nGamma second", encoding="utf-8")

        second_ingest = await client.post("/internal/knowledge-bases/kb-incremental/ingest")
        assert second_ingest.status_code == 202

        status_response = await client.get("/internal/knowledge-bases/kb-incremental/status")
        assert status_response.status_code == 200
        assert status_response.json()["document_count"] == 2
        assert status_response.json()["chunk_count"] == 4

        updated_documents = await repository.list_documents("kb-incremental")
        updated_by_path = {document.relative_path: document for document in updated_documents}
        assert set(updated_by_path) == {"alpha.md", "gamma.txt"}
        assert updated_by_path["alpha.md"].content_hash != initial_by_path["alpha.md"].content_hash

        alpha_chunks = await repository.list_document_chunks(updated_by_path["alpha.md"].document_id)
        gamma_chunks = await repository.list_document_chunks(updated_by_path["gamma.txt"].document_id)
        assert len(alpha_chunks) == 2
        assert len(gamma_chunks) == 2


@pytest.mark.asyncio
async def test_concurrent_ingest_does_not_duplicate_documents_or_chunks_for_same_path(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, app, kb_root):
        (kb_root / "guide.md").write_text("# Intro\n\nAlpha section", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-concurrent",
                "tenant_id": "tenant-a",
                "name": "Concurrent KB",
                "root_path": str(kb_root),
            },
        )
        assert create_response.status_code == 201

        repository = app.state.knowledge_repository
        original_upsert_document = repository.upsert_document
        second_upsert_started = asyncio.Event()
        target_upserts = 0

        async def coordinated_upsert_document(document):
            nonlocal target_upserts
            if document.kb_id == "kb-concurrent" and document.relative_path == "guide.md":
                target_upserts += 1
                if target_upserts == 1:
                    try:
                        await asyncio.wait_for(second_upsert_started.wait(), timeout=0.2)
                    except TimeoutError:
                        pass
                elif target_upserts == 2:
                    second_upsert_started.set()
            await original_upsert_document(document)

        repository.upsert_document = coordinated_upsert_document  # type: ignore[method-assign]
        try:
            await asyncio.gather(
                app.state.knowledge_service.ingest("kb-concurrent"),
                app.state.knowledge_service.ingest("kb-concurrent"),
            )
        finally:
            repository.upsert_document = original_upsert_document  # type: ignore[method-assign]

        documents = await repository.list_documents("kb-concurrent")
        assert len(documents) == 1

        chunks = await repository.list_document_chunks(documents[0].document_id)
        assert len(chunks) == 1

        status_response = await client.get("/internal/knowledge-bases/kb-concurrent/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "success"
        assert status_response.json()["document_count"] == 1
        assert status_response.json()["chunk_count"] == 1


@pytest.mark.asyncio
async def test_shared_db_concurrent_ingest_across_app_instances_converges_to_one_document_and_chunk_set(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    kb_root = tmp_path / "kb-shared"
    kb_root.mkdir()
    (kb_root / "guide.md").write_text("# Intro\n\nAlpha section", encoding="utf-8")

    app_one = create_app(
        db_url=db_url,
        model_client=scripted_supervisor_client,
        embedding_provider=FakeEmbeddingProvider(),
    )
    app_two = create_app(
        db_url=db_url,
        model_client=scripted_supervisor_client,
        embedding_provider=FakeEmbeddingProvider(),
    )

    await app_one.state.ensure_initialized()
    await app_two.state.ensure_initialized()

    try:
        await app_one.state.knowledge_service.register_knowledge_base(
            kb_id="kb-shared",
            tenant_id="tenant-a",
            name="Shared KB",
            root_path=str(kb_root),
            metadata={},
        )

        target_upserts = 0
        second_upsert_started = asyncio.Event()
        target_chunk_replacements = 0
        second_chunk_replace_started = asyncio.Event()

        def wrap_repository_methods(repository):
            original_upsert_document = repository.upsert_document
            original_replace_document_chunks = repository.replace_document_chunks

            async def coordinated_upsert_document(document):
                nonlocal target_upserts
                if document.kb_id == "kb-shared" and document.relative_path == "guide.md":
                    target_upserts += 1
                    if target_upserts == 1:
                        try:
                            await asyncio.wait_for(second_upsert_started.wait(), timeout=0.2)
                        except TimeoutError:
                            pass
                    elif target_upserts == 2:
                        second_upsert_started.set()
                await original_upsert_document(document)

            async def coordinated_replace_document_chunks(document_id, chunks):
                nonlocal target_chunk_replacements
                if len(chunks) == 1 and chunks[0].kb_id == "kb-shared":
                    target_chunk_replacements += 1
                    if target_chunk_replacements == 1:
                        try:
                            await asyncio.wait_for(second_chunk_replace_started.wait(), timeout=0.2)
                        except TimeoutError:
                            pass
                    elif target_chunk_replacements == 2:
                        second_chunk_replace_started.set()
                await original_replace_document_chunks(document_id, chunks)

            repository.upsert_document = coordinated_upsert_document  # type: ignore[method-assign]
            repository.replace_document_chunks = coordinated_replace_document_chunks  # type: ignore[method-assign]
            return original_upsert_document, original_replace_document_chunks

        original_one_upsert, original_one_replace = wrap_repository_methods(app_one.state.knowledge_repository)
        original_two_upsert, original_two_replace = wrap_repository_methods(app_two.state.knowledge_repository)
        try:
            await asyncio.gather(
                app_one.state.knowledge_service.ingest("kb-shared"),
                app_two.state.knowledge_service.ingest("kb-shared"),
            )
        finally:
            app_one.state.knowledge_repository.upsert_document = original_one_upsert  # type: ignore[method-assign]
            app_two.state.knowledge_repository.upsert_document = original_two_upsert  # type: ignore[method-assign]
            app_one.state.knowledge_repository.replace_document_chunks = original_one_replace  # type: ignore[method-assign]
            app_two.state.knowledge_repository.replace_document_chunks = original_two_replace  # type: ignore[method-assign]

        documents = await app_one.state.knowledge_repository.list_documents("kb-shared")
        assert len(documents) == 1

        chunks = await app_one.state.knowledge_repository.list_document_chunks(documents[0].document_id)
        assert len(chunks) == 1

        status = await app_one.state.knowledge_service.get_status("kb-shared")
        assert status.document_count == 1
        assert status.chunk_count == 1
    finally:
        await app_one.state.shutdown_runtime()
        await app_two.state.shutdown_runtime()


@pytest.mark.asyncio
async def test_duplicate_create_rejected_without_resetting_indexed_state(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, kb_root):
        (kb_root / "guide.md").write_text("# Intro\n\nAlpha section", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-duplicate",
                "tenant_id": "tenant-a",
                "name": "Original KB",
                "root_path": str(kb_root),
            },
        )
        assert create_response.status_code == 201

        ingest_response = await client.post("/internal/knowledge-bases/kb-duplicate/ingest")
        assert ingest_response.status_code == 202

        status_after_ingest = await client.get("/internal/knowledge-bases/kb-duplicate/status")
        assert status_after_ingest.status_code == 200
        assert status_after_ingest.json()["status"] == "success"
        assert status_after_ingest.json()["document_count"] == 1
        assert status_after_ingest.json()["chunk_count"] == 1

        duplicate_create = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-duplicate",
                "tenant_id": "tenant-b",
                "name": "Overwriting KB",
                "root_path": str(kb_root / "other"),
            },
        )

        assert duplicate_create.status_code == 409
        assert duplicate_create.json()["detail"] == "knowledge base already exists: kb-duplicate"

        status_after_duplicate = await client.get("/internal/knowledge-bases/kb-duplicate/status")
        assert status_after_duplicate.status_code == 200
        assert status_after_duplicate.json() == status_after_ingest.json()


@pytest.mark.asyncio
async def test_unsupported_only_ingest_marks_knowledge_base_failed(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, kb_root):
        (kb_root / "spreadsheet.csv").write_text("alpha,beta", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-unsupported",
                "tenant_id": "tenant-a",
                "name": "Unsupported KB",
                "root_path": str(kb_root),
            },
        )
        assert create_response.status_code == 201

        ingest_response = await client.post("/internal/knowledge-bases/kb-unsupported/ingest")
        assert ingest_response.status_code == 202

        status_response = await client.get("/internal/knowledge-bases/kb-unsupported/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "failed"
        assert status_response.json()["document_count"] == 0
        assert status_response.json()["chunk_count"] == 0
        assert "spreadsheet.csv" in status_response.json()["last_error"]
        assert "unsupported" in status_response.json()["last_error"]


@pytest.mark.asyncio
async def test_mixed_supported_and_unsupported_ingest_marks_partial_success(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, kb_root):
        (kb_root / "guide.md").write_text("# Intro\n\nAlpha section", encoding="utf-8")
        (kb_root / "spreadsheet.csv").write_text("alpha,beta", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-mixed",
                "tenant_id": "tenant-a",
                "name": "Mixed KB",
                "root_path": str(kb_root),
            },
        )
        assert create_response.status_code == 201

        ingest_response = await client.post("/internal/knowledge-bases/kb-mixed/ingest")
        assert ingest_response.status_code == 202

        status_response = await client.get("/internal/knowledge-bases/kb-mixed/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "partial_success"
        assert status_response.json()["document_count"] == 1
        assert status_response.json()["chunk_count"] == 1
        assert "spreadsheet.csv" in status_response.json()["last_error"]
        assert "unsupported" in status_response.json()["last_error"]


@pytest.mark.asyncio
async def test_knowledge_base_management_can_filter_and_guard_by_tenant(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, kb_root):
        tenant_a_root = kb_root / "tenant-a"
        tenant_b_root = kb_root / "tenant-b"
        tenant_a_root.mkdir()
        tenant_b_root.mkdir()

        for kb_id, tenant_id, root_path in (
            ("kb-tenant-a", "tenant-a", tenant_a_root),
            ("kb-tenant-b", "tenant-b", tenant_b_root),
        ):
            create_response = await client.post(
                "/internal/knowledge-bases",
                json={
                    "kb_id": kb_id,
                    "tenant_id": tenant_id,
                    "name": kb_id,
                    "root_path": str(root_path),
                },
            )
            assert create_response.status_code == 201

        list_response = await client.get("/internal/knowledge-bases", params={"tenant_id": "tenant-a"})
        assert list_response.status_code == 200
        assert [record["kb_id"] for record in list_response.json()] == ["kb-tenant-a"]

        wrong_tenant_status = await client.get(
            "/internal/knowledge-bases/kb-tenant-a/status",
            params={"tenant_id": "tenant-b"},
        )
        assert wrong_tenant_status.status_code == 404
        assert wrong_tenant_status.json()["detail"] == "knowledge base not found for tenant tenant-b: kb-tenant-a"

        wrong_tenant_ingest = await client.post(
            "/internal/knowledge-bases/kb-tenant-a/ingest",
            params={"tenant_id": "tenant-b"},
        )
        assert wrong_tenant_ingest.status_code == 404
        assert wrong_tenant_ingest.json()["detail"] == "knowledge base not found for tenant tenant-b: kb-tenant-a"


@pytest.mark.asyncio
async def test_failed_changed_file_ingest_keeps_previous_document_and_chunks(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(
        tmp_path,
        scripted_supervisor_client,
        embedding_provider=FailingEmbeddingProvider("TRIGGER_FAIL"),
    ) as (client, app, kb_root):
        guide_path = kb_root / "guide.md"
        guide_path.write_text("# Intro\n\nStable section", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-failure",
                "tenant_id": "tenant-a",
                "name": "Failure KB",
                "root_path": str(kb_root),
            },
        )
        assert create_response.status_code == 201

        first_ingest = await client.post("/internal/knowledge-bases/kb-failure/ingest")
        assert first_ingest.status_code == 202

        repository = app.state.knowledge_repository
        original_document = (await repository.list_documents("kb-failure"))[0]
        original_chunks = await repository.list_document_chunks(original_document.document_id)
        assert [chunk.text for chunk in original_chunks] == ["Stable section"]

        query_vector = app.state.embedding_provider.embed_query("Stable section")
        search_before_failure = await app.state.vector_index_provider.search(
            tenant_id="tenant-a",
            kb_ids=["kb-failure"],
            query_vector=query_vector,
            top_k=5,
        )
        assert [hit.text for hit in search_before_failure] == ["Stable section"]

        guide_path.write_text("# Intro\n\nTRIGGER_FAIL updated section", encoding="utf-8")

        failed_ingest = await client.post("/internal/knowledge-bases/kb-failure/ingest")
        assert failed_ingest.status_code == 202

        status_after_failure = await client.get("/internal/knowledge-bases/kb-failure/status")
        assert status_after_failure.status_code == 200
        assert status_after_failure.json()["status"] == "failed"
        assert "embedding failure" in status_after_failure.json()["last_error"]

        documents_after_failure = await repository.list_documents("kb-failure")
        assert len(documents_after_failure) == 1
        assert documents_after_failure[0].document_id == original_document.document_id
        assert documents_after_failure[0].content_hash == original_document.content_hash

        chunks_after_failure = await repository.list_document_chunks(original_document.document_id)
        assert [chunk.text for chunk in chunks_after_failure] == ["Stable section"]

        search_after_failure = await app.state.vector_index_provider.search(
            tenant_id="tenant-a",
            kb_ids=["kb-failure"],
            query_vector=query_vector,
            top_k=5,
        )
        assert [hit.text for hit in search_after_failure] == ["Stable section"]


@pytest.mark.asyncio
async def test_failed_reindex_keeps_last_good_indexed_state(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(
        tmp_path,
        scripted_supervisor_client,
        embedding_provider=FailingEmbeddingProvider("TRIGGER_FAIL"),
    ) as (client, app, kb_root):
        guide_path = kb_root / "guide.md"
        notes_path = kb_root / "notes.txt"
        guide_path.write_text("# Intro\n\nStable section", encoding="utf-8")
        notes_path.write_text("Second stable section", encoding="utf-8")

        create_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-reindex-failure",
                "tenant_id": "tenant-a",
                "name": "Reindex Failure KB",
                "root_path": str(kb_root),
            },
        )
        assert create_response.status_code == 201

        first_ingest = await client.post("/internal/knowledge-bases/kb-reindex-failure/ingest")
        assert first_ingest.status_code == 202

        repository = app.state.knowledge_repository
        original_documents = await repository.list_documents("kb-reindex-failure")
        original_documents_by_path = {document.relative_path: document for document in original_documents}
        original_chunk_texts_by_path: dict[str, list[str]] = {}
        for relative_path, document in original_documents_by_path.items():
            chunks = await repository.list_document_chunks(document.document_id)
            original_chunk_texts_by_path[relative_path] = [chunk.text for chunk in chunks]

        status_before_failure = await client.get("/internal/knowledge-bases/kb-reindex-failure/status")
        assert status_before_failure.status_code == 200
        assert status_before_failure.json()["document_count"] == 2
        assert status_before_failure.json()["chunk_count"] == 2

        query_vector = app.state.embedding_provider.embed_query("Stable section")
        search_before_failure = await app.state.vector_index_provider.search(
            tenant_id="tenant-a",
            kb_ids=["kb-reindex-failure"],
            query_vector=query_vector,
            top_k=5,
        )
        assert {hit.text for hit in search_before_failure} == {"Stable section", "Second stable section"}

        guide_path.write_text("# Intro\n\nTRIGGER_FAIL updated section", encoding="utf-8")

        failed_reindex = await client.post("/internal/knowledge-bases/kb-reindex-failure/reindex")
        assert failed_reindex.status_code == 202

        status_after_failure = await client.get("/internal/knowledge-bases/kb-reindex-failure/status")
        assert status_after_failure.status_code == 200
        assert status_after_failure.json()["status"] == "failed"
        assert "embedding failure" in status_after_failure.json()["last_error"]
        assert status_after_failure.json()["document_count"] == 2
        assert status_after_failure.json()["chunk_count"] == 2

        restored_documents = await repository.list_documents("kb-reindex-failure")
        restored_by_path = {document.relative_path: document for document in restored_documents}
        assert set(restored_by_path) == set(original_documents_by_path)
        for relative_path, original_document in original_documents_by_path.items():
            restored_document = restored_by_path[relative_path]
            assert restored_document.document_id == original_document.document_id
            assert restored_document.content_hash == original_document.content_hash
            restored_chunks = await repository.list_document_chunks(restored_document.document_id)
            assert [chunk.text for chunk in restored_chunks] == original_chunk_texts_by_path[relative_path]

        search_after_failure = await app.state.vector_index_provider.search(
            tenant_id="tenant-a",
            kb_ids=["kb-reindex-failure"],
            query_vector=query_vector,
            top_k=5,
        )
        assert {hit.text for hit in search_after_failure} == {"Stable section", "Second stable section"}


@pytest.mark.asyncio
async def test_knowledge_ingest_and_retrieval_metrics_are_exposed(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(
        tmp_path,
        scripted_supervisor_client,
        embedding_provider=FailingEmbeddingProvider("TRIGGER_FAIL"),
    ) as (client, app, kb_root):
        success_root = kb_root / "success"
        partial_root = kb_root / "partial"
        failed_root = kb_root / "failed"
        success_root.mkdir()
        partial_root.mkdir()
        failed_root.mkdir()

        (success_root / "guide.md").write_text("# Intro\n\nStable section", encoding="utf-8")
        (partial_root / "good.md").write_text("# Intro\n\nUseful section", encoding="utf-8")
        (partial_root / "bad.md").write_text("# Intro\n\nTRIGGER_FAIL broken section", encoding="utf-8")
        (failed_root / "bad.md").write_text("# Intro\n\nTRIGGER_FAIL only section", encoding="utf-8")

        for kb_id, root_path in (
            ("kb-metrics-success", success_root),
            ("kb-metrics-partial", partial_root),
            ("kb-metrics-failed", failed_root),
        ):
            create_response = await client.post(
                "/internal/knowledge-bases",
                json={
                    "kb_id": kb_id,
                    "tenant_id": "tenant-a",
                    "name": kb_id,
                    "root_path": str(root_path),
                },
            )
            assert create_response.status_code == 201

        for kb_id in ("kb-metrics-success", "kb-metrics-partial", "kb-metrics-failed"):
            ingest_response = await client.post(f"/internal/knowledge-bases/{kb_id}/ingest")
            assert ingest_response.status_code == 202

        for kb_id, expected_status in (
            ("kb-metrics-success", "success"),
            ("kb-metrics-partial", "partial_success"),
            ("kb-metrics-failed", "failed"),
        ):
            status_response = await client.get(f"/internal/knowledge-bases/{kb_id}/status")
            assert status_response.status_code == 200
            assert status_response.json()["status"] == expected_status

        retrieval_response = await app.state.retrieval_service.search(
            tenant_id="tenant-a",
            kb_ids=["kb-metrics-success"],
            query="Stable section",
            top_k=5,
            include_compiled_context=True,
        )
        assert [hit.text for hit in retrieval_response.hits] == ["Stable section"]

        with pytest.raises(ValueError, match="top_k must be a positive integer"):
            await app.state.retrieval_service.search(
                tenant_id="tenant-a",
                kb_ids=["kb-metrics-success"],
                query="Stable section",
                top_k=0,
                include_compiled_context=False,
            )

        metrics_response = await client.get("/metrics")
        assert metrics_response.status_code == 200
        metrics_payload = metrics_response.text

        assert 'http_requests_total{method="GET",route="/internal/knowledge-bases/{kb_id}/status",status_code="200"} 3.0' in metrics_payload
        assert 'route="/internal/knowledge-bases/kb-metrics-success/status"' not in metrics_payload
        assert 'knowledge_ingest_requests_total{status="success"} 1.0' in metrics_payload
        assert 'knowledge_ingest_requests_total{status="partial_success"} 1.0' in metrics_payload
        assert 'knowledge_ingest_requests_total{status="failed"} 1.0' in metrics_payload
        assert 'knowledge_retrieval_queries_total{status="success"} 1.0' in metrics_payload
        assert 'knowledge_retrieval_queries_total{status="failed"} 1.0' in metrics_payload
        assert 'knowledge_retrieval_query_duration_seconds_count{status="success"} 1.0' in metrics_payload
        assert 'knowledge_retrieval_query_duration_seconds_count{status="failed"} 1.0' in metrics_payload


@pytest.mark.asyncio
async def test_missing_kb_ingest_records_failed_metric(
    tmp_path: Path,
    scripted_supervisor_client: ScriptedModelClient,
) -> None:
    async with knowledge_api_context(tmp_path, scripted_supervisor_client) as (client, _, _):
        ingest_response = await client.post("/internal/knowledge-bases/kb-missing/ingest")
        assert ingest_response.status_code == 404
        assert ingest_response.json()["detail"] == "knowledge base not found: kb-missing"

        metrics_response = await client.get("/metrics")
        assert metrics_response.status_code == 200
        metrics_payload = metrics_response.text

        assert 'knowledge_ingest_requests_total{status="failed"} 1.0' in metrics_payload
