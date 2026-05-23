from __future__ import annotations

from time import perf_counter

from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.domain.models import RetrievalHitRecord, RetrievalResponseRecord
from agent_runtime.knowledge.providers import EmbeddingProvider, VectorIndexProvider
from agent_runtime.observability.metrics import MetricsSink


class RetrievalService:
    _RETRIEVAL_READY_STATUSES = {"success", "partial_success"}

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        index_provider: VectorIndexProvider,
        knowledge_repository: KnowledgeRepository | None = None,
        metrics_sink: MetricsSink | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._index_provider = index_provider
        self._knowledge_repository = knowledge_repository
        self._metrics_sink = metrics_sink

    async def search(
        self,
        tenant_id: str,
        kb_ids: list[str],
        query: str,
        top_k: int,
        include_compiled_context: bool,
    ) -> RetrievalResponseRecord:
        started = perf_counter()
        try:
            if not kb_ids:
                raise ValueError("kb_ids must contain at least one knowledge base id")
            if top_k <= 0:
                raise ValueError("top_k must be a positive integer")
            await self._ensure_knowledge_bases_ready(tenant_id=tenant_id, kb_ids=kb_ids)

            query_vector = self._embedding_provider.embed_query(query)
            hits = await self._index_provider.search(
                tenant_id=tenant_id,
                kb_ids=kb_ids,
                query_vector=query_vector,
                top_k=top_k,
            )

            response_hits = [
                RetrievalHitRecord(
                    kb_id=hit.kb_id,
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    score=hit.score,
                    text=hit.text,
                    source_locator=hit.source_locator,
                    metadata=self._sanitize_metadata(hit.metadata),
                )
                for hit in hits
            ]

            compiled_context = None
            if include_compiled_context:
                compiled_context = "\n\n".join(hit.text for hit in response_hits)

            response = RetrievalResponseRecord(
                hits=response_hits,
                compiled_context=compiled_context,
                query_metadata={"kb_ids": kb_ids, "top_k": top_k},
            )
        except Exception:
            if self._metrics_sink is not None:
                self._metrics_sink.record_retrieval_query(
                    status="failed",
                    duration_seconds=perf_counter() - started,
                )
            raise

        if self._metrics_sink is not None:
            self._metrics_sink.record_retrieval_query(
                status="success",
                duration_seconds=perf_counter() - started,
            )
        return response

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, object]) -> dict[str, object]:
        sanitized = dict(metadata)
        sanitized.pop("embedding", None)
        return sanitized

    async def _ensure_knowledge_bases_ready(self, *, tenant_id: str, kb_ids: list[str]) -> None:
        if self._knowledge_repository is None:
            return

        for kb_id in kb_ids:
            knowledge_base = await self._knowledge_repository.get_knowledge_base(kb_id, tenant_id=tenant_id)
            if knowledge_base is None:
                raise ValueError(f"knowledge base not found or inaccessible: {kb_id}")
            if knowledge_base.status not in self._RETRIEVAL_READY_STATUSES:
                raise ValueError(
                    f"knowledge base is not ready for retrieval: {kb_id} (status={knowledge_base.status})"
                )
            if knowledge_base.chunk_count <= 0:
                raise ValueError(f"knowledge base has no indexed chunks: {kb_id}")
