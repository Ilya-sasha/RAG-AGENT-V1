from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
from typing import TypeAlias

from agent_runtime.domain.models import ChunkRecord, DocumentRecord, KnowledgeBaseRecord, utc_now
from agent_runtime.knowledge.chunking import StructureFirstChunkingStrategy
from agent_runtime.knowledge.parsers import parse_document
from agent_runtime.knowledge.providers import EmbeddingProvider, VectorIndexProvider
from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.observability.metrics import MetricsSink

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}
KnowledgeSnapshot: TypeAlias = list[tuple[DocumentRecord, list[ChunkRecord]]]


class KnowledgeBaseConflictError(RuntimeError):
    pass


class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embedding_provider: EmbeddingProvider,
        index_provider: VectorIndexProvider,
        chunking_strategy: StructureFirstChunkingStrategy,
        metrics_sink: MetricsSink | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._index_provider = index_provider
        self._chunking_strategy = chunking_strategy
        self._metrics_sink = metrics_sink
        self._kb_locks: dict[str, asyncio.Lock] = {}
        self._kb_locks_guard = asyncio.Lock()

    async def register_knowledge_base(
        self,
        kb_id: str,
        tenant_id: str,
        name: str,
        root_path: str,
        metadata: dict[str, object],
    ) -> KnowledgeBaseRecord:
        existing_record = await self._repository.get_knowledge_base(kb_id)
        if existing_record is not None:
            raise KnowledgeBaseConflictError(f"knowledge base already exists: {kb_id}")

        record = KnowledgeBaseRecord(
            kb_id=kb_id,
            tenant_id=tenant_id,
            name=name,
            root_path=root_path,
            status="registered",
            embedding_provider_id=self._embedding_provider.provider_id(),
            index_provider_id=self._index_provider.provider_id(),
            chunking_strategy="structure-first",
            metadata=dict(metadata),
        )
        await self._repository.upsert_knowledge_base(record)
        return await self.get_status(kb_id)

    async def list_knowledge_bases(self, tenant_id: str | None = None) -> list[KnowledgeBaseRecord]:
        return await self._repository.list_knowledge_bases(tenant_id=tenant_id)

    async def ingest(self, kb_id: str, tenant_id: str | None = None) -> KnowledgeBaseRecord:
        try:
            kb_lock = await self._get_kb_lock(kb_id)
            async with kb_lock:
                knowledge_base = await self.get_status(kb_id, tenant_id=tenant_id)
                result = await self._sync_knowledge_base(knowledge_base, reindex=False)
        except Exception:
            if self._metrics_sink is not None:
                self._metrics_sink.record_knowledge_ingest(status="failed")
            raise

        if self._metrics_sink is not None:
            self._metrics_sink.record_knowledge_ingest(status=result.status)
        return result

    async def reindex(self, kb_id: str, tenant_id: str | None = None) -> KnowledgeBaseRecord:
        kb_lock = await self._get_kb_lock(kb_id)
        async with kb_lock:
            knowledge_base = await self.get_status(kb_id, tenant_id=tenant_id)
            snapshot = await self._snapshot_knowledge_base_documents(kb_id)
            existing_documents = await self._repository.list_documents(kb_id)
            for document in existing_documents:
                await self._delete_document(document.document_id)
            reindex_result = await self._sync_knowledge_base(knowledge_base, reindex=True)
            if reindex_result.status == "success":
                return reindex_result
            if snapshot:
                await self._restore_knowledge_base_snapshot(kb_id, snapshot)
            return await self._update_knowledge_base(
                knowledge_base,
                status="failed",
                last_error=reindex_result.last_error,
            )

    async def get_status(self, kb_id: str, tenant_id: str | None = None) -> KnowledgeBaseRecord:
        knowledge_base = await self._repository.get_knowledge_base(kb_id, tenant_id=tenant_id)
        if knowledge_base is None:
            if tenant_id is not None:
                raise RuntimeError(f"knowledge base not found for tenant {tenant_id}: {kb_id}")
            raise RuntimeError(f"knowledge base not found: {kb_id}")
        return knowledge_base

    async def _sync_knowledge_base(
        self,
        knowledge_base: KnowledgeBaseRecord,
        *,
        reindex: bool,
    ) -> KnowledgeBaseRecord:
        root_path = Path(knowledge_base.root_path)
        if not root_path.exists() or not root_path.is_dir():
            return await self._update_knowledge_base(
                knowledge_base,
                status="failed",
                last_error=f"knowledge base root path not found: {knowledge_base.root_path}",
            )

        existing_documents = await self._repository.list_documents(knowledge_base.kb_id)
        existing_by_path = {document.relative_path: document for document in existing_documents}
        source_files, unsupported_files = self._scan_source_files(root_path)
        source_paths = set(source_files)

        errors: list[str] = []
        warnings: list[str] = []
        indexed_files = 0

        if not reindex:
            deleted_paths = set(existing_by_path) - source_paths
            for relative_path in deleted_paths:
                await self._delete_document(existing_by_path[relative_path].document_id)

        for relative_path, file_path in source_files.items():
            content_hash = self._content_hash(file_path)
            existing_document = existing_by_path.get(relative_path)
            if not reindex and existing_document is not None and existing_document.content_hash == content_hash:
                continue

            previous_document = existing_document.model_copy(deep=True) if existing_document is not None else None
            previous_chunks = (
                await self._repository.list_document_chunks(existing_document.document_id)
                if existing_document is not None
                else []
            )
            document: DocumentRecord | None = None
            try:
                parsed_document = parse_document(file_path)
                chunk_drafts = self._chunking_strategy.split_text(
                    relative_path=relative_path,
                    file_type=parsed_document.file_type,
                    text=parsed_document.text,
                )
                document_kwargs = {}
                if existing_document is not None:
                    document_kwargs["document_id"] = existing_document.document_id
                document = DocumentRecord(
                    kb_id=knowledge_base.kb_id,
                    tenant_id=knowledge_base.tenant_id,
                    relative_path=relative_path,
                    content_hash=content_hash,
                    file_type=parsed_document.file_type,
                    parse_status="indexed",
                    last_indexed_at=utc_now(),
                    error_message=None,
                    metadata=dict(parsed_document.metadata),
                    **document_kwargs,
                )
                await self._repository.upsert_document(document)

                chunks = [
                    ChunkRecord(
                        document_id=document.document_id,
                        kb_id=knowledge_base.kb_id,
                        tenant_id=knowledge_base.tenant_id,
                        chunk_index=draft.chunk_index,
                        text=draft.text,
                        text_length=len(draft.text),
                        token_count=self._estimate_token_count(draft.text),
                        source_locator=draft.source_locator,
                        metadata={},
                    )
                    for draft in chunk_drafts
                ]
                if chunks:
                    embeddings = self._embedding_provider.embed_documents([chunk.text for chunk in chunks])
                    await self._index_provider.upsert_chunks(chunks, embeddings)
                else:
                    await self._repository.replace_document_chunks(document.document_id, [])
                indexed_files += 1
            except Exception as exc:
                if previous_document is not None:
                    await self._restore_document(previous_document, previous_chunks)
                elif document is not None:
                    await self._delete_document(document.document_id)
                errors.append(f"{relative_path}: {exc}")

        if unsupported_files:
            warnings.append(
                "unsupported files skipped: " + ", ".join(unsupported_files)
            )

        status = "success"
        if errors and indexed_files:
            status = "partial_success"
        elif errors:
            status = "failed"
        elif warnings and source_files:
            status = "partial_success"
        elif warnings:
            status = "failed"

        issues = [*errors, *warnings]

        return await self._update_knowledge_base(
            knowledge_base,
            status=status,
            last_error="; ".join(issues) if issues else None,
        )

    async def _update_knowledge_base(
        self,
        knowledge_base: KnowledgeBaseRecord,
        *,
        status: str,
        last_error: str | None,
    ) -> KnowledgeBaseRecord:
        current_record = await self._repository.get_knowledge_base(knowledge_base.kb_id)
        if current_record is None:
            raise RuntimeError(f"knowledge base not found: {knowledge_base.kb_id}")
        updated_record = current_record.model_copy(update={"status": status, "last_error": last_error})
        await self._repository.upsert_knowledge_base(updated_record)
        refreshed_record = await self._repository.get_knowledge_base(knowledge_base.kb_id)
        if refreshed_record is None:
            raise RuntimeError(f"knowledge base not found: {knowledge_base.kb_id}")
        return refreshed_record

    async def _delete_document(self, document_id: str) -> None:
        await self._index_provider.delete_document(document_id)
        await self._repository.delete_document(document_id)

    async def _restore_document(
        self,
        previous_document: DocumentRecord,
        previous_chunks: list[ChunkRecord],
    ) -> None:
        await self._repository.upsert_document(previous_document)
        if previous_chunks:
            embeddings = [self._chunk_embedding(chunk) for chunk in previous_chunks]
            await self._index_provider.upsert_chunks(previous_chunks, embeddings)
        else:
            await self._repository.replace_document_chunks(previous_document.document_id, [])

    async def _snapshot_knowledge_base_documents(self, kb_id: str) -> KnowledgeSnapshot:
        snapshot: KnowledgeSnapshot = []
        for document in await self._repository.list_documents(kb_id):
            chunks = await self._repository.list_document_chunks(document.document_id)
            snapshot.append((document.model_copy(deep=True), [chunk.model_copy(deep=True) for chunk in chunks]))
        return snapshot

    async def _restore_knowledge_base_snapshot(
        self,
        kb_id: str,
        snapshot: KnowledgeSnapshot,
    ) -> None:
        for document in await self._repository.list_documents(kb_id):
            await self._delete_document(document.document_id)
        for document, chunks in snapshot:
            await self._restore_document(document, chunks)

    @staticmethod
    def _scan_source_files(root_path: Path) -> tuple[dict[str, Path], list[str]]:
        files: dict[str, Path] = {}
        unsupported_files: list[str] = []
        for file_path in sorted(path for path in root_path.rglob("*") if path.is_file()):
            relative_path = file_path.relative_to(root_path).as_posix()
            if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                unsupported_files.append(relative_path)
                continue
            files[relative_path] = file_path
        return files, unsupported_files

    @staticmethod
    def _content_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _estimate_token_count(text: str) -> int:
        return len(text.split())

    @staticmethod
    def _chunk_embedding(chunk: ChunkRecord) -> list[float]:
        embedding = chunk.metadata.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError(f"chunk embedding missing for chunk: {chunk.chunk_id}")
        return [float(value) for value in embedding]

    async def _get_kb_lock(self, kb_id: str) -> asyncio.Lock:
        async with self._kb_locks_guard:
            kb_lock = self._kb_locks.get(kb_id)
            if kb_lock is None:
                kb_lock = asyncio.Lock()
                self._kb_locks[kb_id] = kb_lock
            return kb_lock
