import asyncio
from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind, EventType, RunStatus, ToolInvocationStatus
from agent_runtime.domain.models import TenantPolicyRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


async def _wait_for_run_completion(client, run_id: str) -> dict[str, object]:
    payload: dict[str, object] = {}
    for _ in range(20):
        response = await client.get(f"/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] == RunStatus.COMPLETED.value:
            return payload
        await asyncio.sleep(0.05)
    return payload


@pytest.mark.asyncio
async def test_rag_search_tool_executes_through_gateway_and_persists_output(tmp_path: Path) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    (kb_root / "guide.md").write_text("# Intro\n\nAlpha retrieval text", encoding="utf-8")
    (kb_root / "notes.txt").write_text("Beta retrieval text", encoding="utf-8")

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="search the knowledge base",
                        tool_name="rag_search",
                        tool_arguments={
                            "kb_ids": ["kb-rag"],
                            "query": "Alpha retrieval text",
                            "top_k": 2,
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
        embedding_provider=FakeEmbeddingProvider(),
    )
    await app.state.ensure_initialized()

    await app.state.knowledge_service.register_knowledge_base(
        kb_id="kb-rag",
        tenant_id="tenant-a",
        name="RAG KB",
        root_path=str(kb_root),
        metadata={},
    )
    await app.state.knowledge_service.ingest("kb-rag")

    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["rag_search"],
            approval_required_tools=[],
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "search docs"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        run_payload = await _wait_for_run_completion(client, run_id)
        metrics_response = await client.get("/metrics")

    assert run_payload["status"] == RunStatus.COMPLETED.value
    assert run_payload["result"] == "retrieval complete"
    assert metrics_response.status_code == 200
    assert 'knowledge_retrieval_queries_total{status="success"} 1.0' in metrics_response.text
    assert 'knowledge_retrieval_query_duration_seconds_count{status="success"} 1.0' in metrics_response.text

    tool_definition = await repository.get_tool_definition("rag_search")
    events = await repository.list_events(run_id)
    tool_called_event = next(event for event in events if event.event_type == EventType.TOOL_CALLED)
    invocation = await repository.get_tool_invocation(tool_called_event.payload["invocation_id"])

    assert tool_definition is not None
    assert tool_definition.input_schema["required"] == ["kb_ids", "query"]
    assert tool_definition.input_schema["properties"]["kb_ids"]["minItems"] == 1
    assert tool_definition.input_schema["properties"]["top_k"]["minimum"] == 1
    assert invocation is not None
    assert invocation.status == ToolInvocationStatus.COMPLETED
    assert invocation.arguments == {
        "kb_ids": ["kb-rag"],
        "query": "Alpha retrieval text",
        "top_k": 2,
        "include_compiled_context": True,
    }
    assert invocation.result is not None
    assert invocation.result["query_metadata"] == {"kb_ids": ["kb-rag"], "top_k": 2}
    assert invocation.result["compiled_context"] == "Alpha retrieval text\n\nBeta retrieval text"
    assert [hit["kb_id"] for hit in invocation.result["hits"]] == ["kb-rag", "kb-rag"]
    assert all("embedding" not in hit["metadata"] for hit in invocation.result["hits"])
