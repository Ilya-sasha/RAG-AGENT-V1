from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from agent_runtime.domain.models import ChunkRecord


class EmbeddingProvider(Protocol):
    def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, query: str) -> list[float]:
        ...

    def provider_id(self) -> str:
        ...


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
    async def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        ...

    async def delete_document(self, document_id: str) -> None:
        ...

    async def search(
        self,
        tenant_id: str,
        kb_ids: list[str],
        query_vector: list[float],
        top_k: int,
    ) -> list[VectorSearchHit]:
        ...

    async def get_index_stats(self, kb_id: str) -> dict[str, int]:
        ...

    def provider_id(self) -> str:
        ...
