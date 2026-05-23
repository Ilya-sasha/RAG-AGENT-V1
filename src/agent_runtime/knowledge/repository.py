from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.domain.models import ChunkRecord, DocumentRecord, KnowledgeBaseRecord, utc_now
from agent_runtime.state.tables import KnowledgeBaseTable, KnowledgeChunkTable, KnowledgeDocumentTable


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
                if row.tenant_id != record.tenant_id:
                    raise ValueError(
                        f"knowledge base tenant_id mismatch for {record.kb_id}: {record.tenant_id}"
                    )
                row.tenant_id = record.tenant_id
                row.name = record.name
                row.root_path = record.root_path
                row.status = record.status
                row.embedding_provider_id = record.embedding_provider_id
                row.index_provider_id = record.index_provider_id
                row.chunking_strategy = record.chunking_strategy
                row.document_count = record.document_count
                row.chunk_count = record.chunk_count
                row.last_error = record.last_error
                row.metadata_json = record.metadata
                row.updated_at = utc_now()
            await session.commit()

    async def get_knowledge_base(
        self,
        kb_id: str,
        tenant_id: str | None = None,
    ) -> KnowledgeBaseRecord | None:
        async with self._session_factory() as session:
            row = await session.get(KnowledgeBaseTable, kb_id)
            if row is None:
                return None
            if tenant_id is not None and row.tenant_id != tenant_id:
                return None
            return self._map_knowledge_base(row)

    async def list_knowledge_bases(self, tenant_id: str | None = None) -> list[KnowledgeBaseRecord]:
        async with self._session_factory() as session:
            query = select(KnowledgeBaseTable).order_by(KnowledgeBaseTable.created_at, KnowledgeBaseTable.kb_id)
            if tenant_id is not None:
                query = query.where(KnowledgeBaseTable.tenant_id == tenant_id)
            rows = (await session.execute(query)).scalars()
            return [self._map_knowledge_base(row) for row in rows]

    async def upsert_document(self, record: DocumentRecord) -> None:
        async with self._session_factory() as session:
            row = await session.get(KnowledgeDocumentTable, record.document_id)
            if row is None:
                row = await self._get_document_by_path(session, record.kb_id, record.relative_path)
            if row is None:
                row = KnowledgeDocumentTable(
                    document_id=record.document_id,
                    kb_id=record.kb_id,
                    tenant_id=record.tenant_id,
                    relative_path=record.relative_path,
                    content_hash=record.content_hash,
                    file_type=record.file_type,
                    parse_status=record.parse_status,
                    last_indexed_at=record.last_indexed_at,
                    error_message=record.error_message,
                    metadata_json=record.metadata,
                )
                session.add(row)
                record.document_id = row.document_id
                try:
                    await self._refresh_kb_counts(session, record.kb_id)
                    await session.commit()
                    return
                except IntegrityError:
                    await session.rollback()
                    row = await self._get_document_by_path(session, record.kb_id, record.relative_path)
                    if row is None:
                        raise

            await self._apply_document_record(session, row, record)
            await session.commit()

    async def list_documents(self, kb_id: str) -> list[DocumentRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(KnowledgeDocumentTable)
                    .where(KnowledgeDocumentTable.kb_id == kb_id)
                    .order_by(KnowledgeDocumentTable.relative_path, KnowledgeDocumentTable.document_id)
                )
            ).scalars()
            return [self._map_document(row) for row in rows]

    async def replace_document_chunks(self, document_id: str, chunks: Sequence[ChunkRecord]) -> None:
        async with self._session_factory() as session:
            for attempt in range(2):
                document = await session.get(KnowledgeDocumentTable, document_id)
                if document is None:
                    raise RuntimeError(f"document not found: {document_id}")
                prepared_chunks: list[tuple[ChunkRecord, list[float], dict]] = []
                for chunk in chunks:
                    if chunk.document_id != document_id:
                        raise ValueError(f"chunk document_id mismatch for chunk {chunk.chunk_id}: {chunk.document_id}")
                    if chunk.kb_id != document.kb_id:
                        raise ValueError(f"chunk kb_id mismatch for chunk {chunk.chunk_id}: {chunk.kb_id}")
                    if chunk.tenant_id != document.tenant_id:
                        raise ValueError(f"chunk tenant_id mismatch for chunk {chunk.chunk_id}: {chunk.tenant_id}")

                    embedding = chunk.metadata.get("embedding")
                    if not isinstance(embedding, list):
                        raise RuntimeError(f"chunk embedding missing for chunk: {chunk.chunk_id}")
                    metadata = dict(chunk.metadata)
                    metadata.pop("embedding", None)
                    prepared_chunks.append((chunk, embedding, metadata))

                try:
                    await session.execute(delete(KnowledgeChunkTable).where(KnowledgeChunkTable.document_id == document_id))
                    for chunk, embedding, metadata in prepared_chunks:
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
                                embedding=embedding,
                                metadata_json=metadata,
                            )
                        )
                    await self._refresh_kb_counts(session, document.kb_id)
                    await session.commit()
                    return
                except IntegrityError:
                    await session.rollback()
                    if attempt == 1:
                        raise

    async def list_document_chunks(self, document_id: str) -> list[ChunkRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(KnowledgeChunkTable)
                    .where(KnowledgeChunkTable.document_id == document_id)
                    .order_by(KnowledgeChunkTable.chunk_index, KnowledgeChunkTable.chunk_id)
                )
            ).scalars()
            return [self._map_chunk(row) for row in rows]

    async def list_searchable_chunks(self, tenant_id: str, kb_ids: Sequence[str]) -> list[ChunkRecord]:
        if not kb_ids:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(KnowledgeChunkTable)
                    .where(KnowledgeChunkTable.tenant_id == tenant_id)
                    .where(KnowledgeChunkTable.kb_id.in_(kb_ids))
                    .order_by(
                        KnowledgeChunkTable.kb_id,
                        KnowledgeChunkTable.document_id,
                        KnowledgeChunkTable.chunk_index,
                    )
                )
            ).scalars()
            return [self._map_chunk(row) for row in rows]

    async def delete_document(self, document_id: str) -> None:
        async with self._session_factory() as session:
            document = await session.get(KnowledgeDocumentTable, document_id)
            if document is None:
                return
            await session.execute(delete(KnowledgeChunkTable).where(KnowledgeChunkTable.document_id == document_id))
            await session.delete(document)
            await self._refresh_kb_counts(session, document.kb_id)
            await session.commit()

    async def _refresh_kb_counts(self, session: AsyncSession, kb_id: str) -> None:
        kb_row = await session.get(KnowledgeBaseTable, kb_id)
        if kb_row is None:
            raise RuntimeError(f"knowledge base not found: {kb_id}")

        document_count = await session.scalar(
            select(func.count()).select_from(KnowledgeDocumentTable).where(KnowledgeDocumentTable.kb_id == kb_id)
        )
        chunk_count = await session.scalar(
            select(func.count()).select_from(KnowledgeChunkTable).where(KnowledgeChunkTable.kb_id == kb_id)
        )

        kb_row.document_count = int(document_count or 0)
        kb_row.chunk_count = int(chunk_count or 0)
        kb_row.updated_at = utc_now()

    @staticmethod
    def _map_knowledge_base(row: KnowledgeBaseTable) -> KnowledgeBaseRecord:
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

    @staticmethod
    def _map_document(row: KnowledgeDocumentTable) -> DocumentRecord:
        return DocumentRecord(
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

    @staticmethod
    def _map_chunk(row: KnowledgeChunkTable) -> ChunkRecord:
        metadata = dict(row.metadata_json)
        metadata["embedding"] = row.embedding
        return ChunkRecord(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            kb_id=row.kb_id,
            tenant_id=row.tenant_id,
            chunk_index=row.chunk_index,
            text=row.text,
            text_length=row.text_length,
            token_count=row.token_count,
            source_locator=row.source_locator,
            metadata=metadata,
        )

    async def _get_document_by_path(
        self,
        session: AsyncSession,
        kb_id: str,
        relative_path: str,
    ) -> KnowledgeDocumentTable | None:
        return await session.scalar(
            select(KnowledgeDocumentTable)
            .where(KnowledgeDocumentTable.kb_id == kb_id)
            .where(KnowledgeDocumentTable.relative_path == relative_path)
        )

    async def _apply_document_record(
        self,
        session: AsyncSession,
        row: KnowledgeDocumentTable,
        record: DocumentRecord,
    ) -> None:
        if row.tenant_id != record.tenant_id:
            raise ValueError(f"document tenant_id mismatch for {row.document_id}: {record.tenant_id}")

        previous_kb_id = row.kb_id
        kb_changed = previous_kb_id != record.kb_id
        if kb_changed:
            await session.execute(delete(KnowledgeChunkTable).where(KnowledgeChunkTable.document_id == row.document_id))

        row.kb_id = record.kb_id
        row.tenant_id = record.tenant_id
        row.relative_path = record.relative_path
        row.content_hash = record.content_hash
        row.file_type = record.file_type
        row.parse_status = record.parse_status
        row.last_indexed_at = record.last_indexed_at
        row.error_message = record.error_message
        row.metadata_json = record.metadata
        record.document_id = row.document_id

        if kb_changed:
            await self._refresh_kb_counts(session, previous_kb_id)
            await self._refresh_kb_counts(session, record.kb_id)
        else:
            await self._refresh_kb_counts(session, record.kb_id)
