from __future__ import annotations

from math import sqrt

from agent_runtime.domain.models import ChunkRecord
from agent_runtime.knowledge.providers import VectorSearchHit
from agent_runtime.knowledge.repository import KnowledgeRepository


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_magnitude = sqrt(sum(value * value for value in left))
    right_magnitude = sqrt(sum(value * value for value in right))
    if left_magnitude == 0.0 or right_magnitude == 0.0:
        return 0.0
    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    return dot_product / (left_magnitude * right_magnitude)


class LocalPersistentVectorIndexProvider:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    def provider_id(self) -> str:
        return "sqlite-local"

    async def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunk and embedding counts must match")
        if not chunks:
            return
        document_ids = {chunk.document_id for chunk in chunks}
        if len(document_ids) != 1:
            raise ValueError("all chunks in an upsert batch must belong to the same document_id")

        prepared_chunks = [
            chunk.model_copy(update={"metadata": {**chunk.metadata, "embedding": embedding}})
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        await self._repository.replace_document_chunks(chunks[0].document_id, prepared_chunks)

    async def delete_document(self, document_id: str) -> None:
        await self._repository.delete_document(document_id)

    async def search(
        self,
        tenant_id: str,
        kb_ids: list[str],
        query_vector: list[float],
        top_k: int,
    ) -> list[VectorSearchHit]:
        chunks = await self._repository.list_searchable_chunks(tenant_id, kb_ids)
        scored_hits: list[VectorSearchHit] = []
        for chunk in chunks:
            embedding = chunk.metadata.get("embedding")
            if not isinstance(embedding, list):
                continue
            score = _cosine_similarity(query_vector, [float(value) for value in embedding])
            metadata = dict(chunk.metadata)
            metadata.pop("embedding", None)
            scored_hits.append(
                VectorSearchHit(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    kb_id=chunk.kb_id,
                    tenant_id=chunk.tenant_id,
                    score=score,
                    text=chunk.text,
                    source_locator=chunk.source_locator,
                    metadata=metadata,
                )
            )

        scored_hits.sort(key=lambda hit: hit.score, reverse=True)
        return scored_hits[:top_k]

    async def get_index_stats(self, kb_id: str) -> dict[str, int]:
        knowledge_base = await self._repository.get_knowledge_base(kb_id)
        if knowledge_base is None:
            return {"document_count": 0, "chunk_count": 0}
        return {
            "document_count": knowledge_base.document_count,
            "chunk_count": knowledge_base.chunk_count,
        }
