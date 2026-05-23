import pytest

from agent_runtime.domain.models import KnowledgeBaseRecord
from agent_runtime.knowledge.providers import VectorSearchHit
from agent_runtime.observability.metrics import PrometheusMetricsSink
from agent_runtime.retrieval.service import RetrievalService
from agent_runtime.tools.base import ToolExecutionRequest
from agent_runtime.tools.rag_search import RagSearchToolExecutor


class StubEmbeddingProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.25, 0.75]


class FakeIndexProvider:
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self.hits = hits
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        tenant_id: str,
        kb_ids: list[str],
        query_vector: list[float],
        top_k: int,
    ) -> list[VectorSearchHit]:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "kb_ids": kb_ids,
                "query_vector": query_vector,
                "top_k": top_k,
            }
        )
        return self.hits


class FakeKnowledgeRepository:
    def __init__(self, knowledge_bases: dict[str, KnowledgeBaseRecord]) -> None:
        self.knowledge_bases = knowledge_bases
        self.calls: list[tuple[str, str | None]] = []

    async def get_knowledge_base(
        self,
        kb_id: str,
        tenant_id: str | None = None,
    ) -> KnowledgeBaseRecord | None:
        self.calls.append((kb_id, tenant_id))
        record = self.knowledge_bases.get(kb_id)
        if record is None:
            return None
        if tenant_id is not None and record.tenant_id != tenant_id:
            return None
        return record


@pytest.mark.asyncio
async def test_search_returns_structured_hits_and_compiled_context() -> None:
    embedding_provider = StubEmbeddingProvider()
    index_provider = FakeIndexProvider(
        [
            VectorSearchHit(
                chunk_id="chunk-1",
                document_id="doc-1",
                kb_id="kb-a",
                tenant_id="tenant-a",
                score=0.98,
                text="Alpha section",
                source_locator={"path": "guide.md"},
                metadata={"title": "Guide", "embedding": [9.0, 9.0]},
            ),
            VectorSearchHit(
                chunk_id="chunk-2",
                document_id="doc-2",
                kb_id="kb-b",
                tenant_id="tenant-a",
                score=0.76,
                text="Beta section",
                source_locator={"path": "notes.txt"},
                metadata={"tag": "notes"},
            ),
        ]
    )
    service = RetrievalService(embedding_provider, index_provider)

    response = await service.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a", "kb-b"],
        query="alpha beta",
        top_k=3,
        include_compiled_context=True,
    )

    assert embedding_provider.queries == ["alpha beta"]
    assert index_provider.calls == [
        {
            "tenant_id": "tenant-a",
            "kb_ids": ["kb-a", "kb-b"],
            "query_vector": [0.25, 0.75],
            "top_k": 3,
        }
    ]
    assert [hit.chunk_id for hit in response.hits] == ["chunk-1", "chunk-2"]
    assert response.hits[0].metadata == {"title": "Guide"}
    assert response.hits[1].metadata == {"tag": "notes"}
    assert response.compiled_context == "Alpha section\n\nBeta section"
    assert response.query_metadata == {"kb_ids": ["kb-a", "kb-b"], "top_k": 3}


@pytest.mark.asyncio
async def test_search_omits_compiled_context_when_not_requested() -> None:
    service = RetrievalService(
        StubEmbeddingProvider(),
        FakeIndexProvider(
            [
                VectorSearchHit(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    kb_id="kb-a",
                    tenant_id="tenant-a",
                    score=0.5,
                    text="Only hit",
                    source_locator={"path": "guide.md"},
                )
            ]
        ),
    )

    response = await service.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query="only",
        top_k=1,
        include_compiled_context=False,
    )

    assert response.compiled_context is None
    assert response.query_metadata == {"kb_ids": ["kb-a"], "top_k": 1}


@pytest.mark.asyncio
async def test_search_rejects_non_positive_top_k() -> None:
    service = RetrievalService(
        StubEmbeddingProvider(),
        FakeIndexProvider([]),
    )

    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        await service.search(
            tenant_id="tenant-a",
            kb_ids=["kb-a"],
            query="only",
            top_k=0,
            include_compiled_context=False,
        )


@pytest.mark.asyncio
async def test_search_rejects_empty_kb_ids() -> None:
    service = RetrievalService(
        StubEmbeddingProvider(),
        FakeIndexProvider([]),
    )

    with pytest.raises(ValueError, match="kb_ids"):
        await service.search(
            tenant_id="tenant-a",
            kb_ids=[],
            query="only",
            top_k=1,
            include_compiled_context=False,
        )


@pytest.mark.asyncio
async def test_search_rejects_failed_knowledge_base_before_embedding() -> None:
    embedding_provider = StubEmbeddingProvider()
    service = RetrievalService(
        embedding_provider,
        FakeIndexProvider([]),
        knowledge_repository=FakeKnowledgeRepository(
            {
                "kb-a": KnowledgeBaseRecord(
                    kb_id="kb-a",
                    tenant_id="tenant-a",
                    name="KB A",
                    root_path="C:/kb-a",
                    status="failed",
                    embedding_provider_id="local-default",
                    index_provider_id="sqlite-local",
                    chunking_strategy="structure-first",
                    last_error="ingest failed",
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="kb-a"):
        await service.search(
            tenant_id="tenant-a",
            kb_ids=["kb-a"],
            query="only",
            top_k=1,
            include_compiled_context=False,
        )

    assert embedding_provider.queries == []


@pytest.mark.asyncio
async def test_search_rejects_empty_knowledge_base_before_embedding() -> None:
    embedding_provider = StubEmbeddingProvider()
    service = RetrievalService(
        embedding_provider,
        FakeIndexProvider([]),
        knowledge_repository=FakeKnowledgeRepository(
            {
                "kb-a": KnowledgeBaseRecord(
                    kb_id="kb-a",
                    tenant_id="tenant-a",
                    name="KB A",
                    root_path="C:/kb-a",
                    status="success",
                    embedding_provider_id="local-default",
                    index_provider_id="sqlite-local",
                    chunking_strategy="structure-first",
                    chunk_count=0,
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="kb-a"):
        await service.search(
            tenant_id="tenant-a",
            kb_ids=["kb-a"],
            query="only",
            top_k=1,
            include_compiled_context=False,
        )

    assert embedding_provider.queries == []


@pytest.mark.asyncio
async def test_search_records_success_metrics_when_sink_is_configured() -> None:
    metrics_sink = PrometheusMetricsSink()
    service = RetrievalService(
        StubEmbeddingProvider(),
        FakeIndexProvider(
            [
                VectorSearchHit(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    kb_id="kb-a",
                    tenant_id="tenant-a",
                    score=0.5,
                    text="Only hit",
                    source_locator={"path": "guide.md"},
                )
            ]
        ),
        metrics_sink=metrics_sink,
    )

    await service.search(
        tenant_id="tenant-a",
        kb_ids=["kb-a"],
        query="only",
        top_k=1,
        include_compiled_context=False,
    )

    payload = metrics_sink.render_prometheus_text()

    assert 'knowledge_retrieval_queries_total{status="success"} 1.0' in payload
    assert 'knowledge_retrieval_query_duration_seconds_count{status="success"} 1.0' in payload


@pytest.mark.asyncio
async def test_search_records_failed_metrics_when_query_validation_fails() -> None:
    metrics_sink = PrometheusMetricsSink()
    service = RetrievalService(
        StubEmbeddingProvider(),
        FakeIndexProvider([]),
        metrics_sink=metrics_sink,
    )

    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        await service.search(
            tenant_id="tenant-a",
            kb_ids=["kb-a"],
            query="only",
            top_k=0,
            include_compiled_context=False,
        )

    payload = metrics_sink.render_prometheus_text()

    assert 'knowledge_retrieval_queries_total{status="failed"} 1.0' in payload
    assert 'knowledge_retrieval_query_duration_seconds_count{status="failed"} 1.0' in payload


@pytest.mark.asyncio
async def test_rag_search_executor_rejects_string_kb_ids() -> None:
    executor = RagSearchToolExecutor(RetrievalService(StubEmbeddingProvider(), FakeIndexProvider([])))

    with pytest.raises(ValueError, match="kb_ids"):
        await executor.execute(
            ToolExecutionRequest(
                tenant_id="tenant-a",
                run_id="run-1",
                agent_id="agent-1",
                tool_name="rag_search",
                arguments={"kb_ids": "kb-a", "query": "alpha"},
            )
        )


@pytest.mark.asyncio
async def test_rag_search_executor_rejects_empty_kb_ids() -> None:
    executor = RagSearchToolExecutor(RetrievalService(StubEmbeddingProvider(), FakeIndexProvider([])))

    with pytest.raises(ValueError, match="kb_ids"):
        await executor.execute(
            ToolExecutionRequest(
                tenant_id="tenant-a",
                run_id="run-1",
                agent_id="agent-1",
                tool_name="rag_search",
                arguments={"kb_ids": [], "query": "alpha"},
            )
        )


@pytest.mark.asyncio
async def test_rag_search_executor_rejects_non_boolean_compiled_context_flag() -> None:
    executor = RagSearchToolExecutor(RetrievalService(StubEmbeddingProvider(), FakeIndexProvider([])))

    with pytest.raises(ValueError, match="include_compiled_context"):
        await executor.execute(
            ToolExecutionRequest(
                tenant_id="tenant-a",
                run_id="run-1",
                agent_id="agent-1",
                tool_name="rag_search",
                arguments={"kb_ids": ["kb-a"], "query": "alpha", "include_compiled_context": "false"},
            )
        )


@pytest.mark.asyncio
async def test_rag_search_executor_rejects_non_positive_top_k() -> None:
    executor = RagSearchToolExecutor(RetrievalService(StubEmbeddingProvider(), FakeIndexProvider([])))

    with pytest.raises(ValueError, match="top_k"):
        await executor.execute(
            ToolExecutionRequest(
                tenant_id="tenant-a",
                run_id="run-1",
                agent_id="agent-1",
                tool_name="rag_search",
                arguments={"kb_ids": ["kb-a"], "query": "alpha", "top_k": 0},
            )
        )
