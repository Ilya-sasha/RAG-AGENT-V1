from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind, EventType
from agent_runtime.domain.models import ApprovalRequestRecord, TenantPolicyRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


async def _wait_for_run_status(client, run_id: str, status: str) -> dict[str, object]:
    payload: dict[str, object] = {}
    for _ in range(20):
        response = await client.get(f"/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    return payload


@pytest.mark.asyncio
async def test_assistant_session_chat_and_activity_routes(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="reply",
                        final_output="assistant says hello",
                    )
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/assistant/sessions",
            json={
                "tenant_id": "tenant-a",
                "mode": "chat",
                "title": "Ops Chat",
            },
        )
        assert create_response.status_code == 201
        session_payload = create_response.json()
        session_id = session_payload["session_id"]
        assert session_payload["tenant_id"] == "tenant-a"
        assert session_payload["mode"] == "chat"
        assert session_payload["title"] == "Ops Chat"
        assert session_payload["status"] == "active"

        list_response = await client.get("/v1/assistant/sessions", params={"tenant_id": "tenant-a"})
        assert list_response.status_code == 200
        assert list_response.json() == [session_payload]

        chat_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/chat",
            json={
                "tenant_id": "tenant-a",
                "content": "hello",
                "knowledge_base_ids": ["kb-ops"],
            },
        )
        assert chat_response.status_code == 200
        chat_payload = chat_response.json()
        assert chat_payload["status"] == "completed"
        assert chat_payload["run_id"] is not None
        assert chat_payload["user_message"]["role"] == "user"
        assert chat_payload["assistant_message"]["role"] == "assistant"
        assert chat_payload["assistant_message"]["content"] == "assistant says hello"

        messages_response = await client.get(
            f"/v1/assistant/sessions/{session_id}/messages",
            params={"tenant_id": "tenant-a"},
        )
        assert messages_response.status_code == 200
        messages_payload = messages_response.json()
        assert isinstance(messages_payload, list)
        assert [message["role"] for message in messages_payload] == ["user", "assistant"]

        activity_response = await client.get(
            f"/v1/assistant/sessions/{session_id}/activity",
            params={"tenant_id": "tenant-a"},
        )
        assert activity_response.status_code == 200
        activity_payload = activity_response.json()
        assert [message["role"] for message in activity_payload["messages"]] == ["user", "assistant"]
        assert activity_payload["linked_runs"][0]["run_id"] == chat_payload["run_id"]
        assert activity_payload["linked_runs"][0]["launch_kind"] == "chat"
        assert activity_payload["linked_runs"][0]["run_status"] == "completed"


@pytest.mark.asyncio
async def test_assistant_session_creation_rejects_invalid_mode(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        response = await client.post(
            "/v1/assistant/sessions",
            json={
                "tenant_id": "tenant-a",
                "mode": "invalid",
                "title": "Bad Session",
            },
        )

        assert response.status_code == 422


@pytest.mark.asyncio
async def test_assistant_missing_session_routes_return_404(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        messages_response = await client.get(
            "/v1/assistant/sessions/missing/messages",
            params={"tenant_id": "tenant-a"},
        )
        assert messages_response.status_code == 404
        assert messages_response.json() == {"detail": "assistant session not found: missing"}

        chat_response = await client.post(
            "/v1/assistant/sessions/missing/chat",
            json={
                "tenant_id": "tenant-a",
                "content": "hello",
            },
        )
        assert chat_response.status_code == 404
        assert chat_response.json() == {"detail": "assistant session not found: missing"}

        activity_response = await client.get(
            "/v1/assistant/sessions/missing/activity",
            params={"tenant_id": "tenant-a"},
        )
        assert activity_response.status_code == 404
        assert activity_response.json() == {"detail": "assistant session not found: missing"}


@pytest.mark.asyncio
async def test_assistant_task_route_returns_linked_run_id(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="task finished",
                    )
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/assistant/sessions",
            json={
                "tenant_id": "tenant-a",
                "mode": "task",
                "title": "Ops Tasks",
            },
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        task_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/tasks",
            json={
                "tenant_id": "tenant-a",
                "objective": "Triage incident INC-42",
            },
        )
        assert task_response.status_code == 201
        task_payload = task_response.json()
        assert task_payload["run_id"] is not None
        assert task_payload["request_message"]["content"] == "Triage incident INC-42"
        assert task_payload["request_message"]["structured_payload"] == {"kind": "task_request"}

        completed_payload = await _wait_for_run_status(client, task_payload["run_id"], "completed")
        assert completed_payload["status"] == "completed"

        activity_response = await client.get(
            f"/v1/assistant/sessions/{session_id}/activity",
            params={"tenant_id": "tenant-a"},
        )
        assert activity_response.status_code == 200
        activity_payload = activity_response.json()
        assert activity_payload["linked_runs"][0]["run_id"] == task_payload["run_id"]
        assert activity_payload["linked_runs"][0]["launch_kind"] == "task"


@pytest.mark.asyncio
async def test_assistant_activity_route_includes_pending_approval_summary(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="task finished",
                    )
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/assistant/sessions",
            json={
                "tenant_id": "tenant-a",
                "mode": "task",
                "title": "Ops Tasks",
            },
        )
        session_id = create_response.json()["session_id"]

        task_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/tasks",
            json={
                "tenant_id": "tenant-a",
                "objective": "Triage incident INC-42",
            },
        )
        run_id = task_response.json()["run_id"]

        await app.state.run_service.resume_run(run_id)
        await app.state.run_service._repository.create_approval_request(
            ApprovalRequestRecord(
                tenant_id="tenant-a",
                run_id=run_id,
                agent_id="agent-1",
                tool_name="rag_search",
                reason="Need approval for kb scope",
            )
        )

        activity_response = await client.get(
            f"/v1/assistant/sessions/{session_id}/activity",
            params={"tenant_id": "tenant-a"},
        )

        assert activity_response.status_code == 200
        activity_payload = activity_response.json()
        assert activity_payload["linked_runs"][0]["pending_approval"] == {
            "approval_id": activity_payload["linked_runs"][0]["pending_approval"]["approval_id"],
            "agent_id": "agent-1",
            "tool_name": "rag_search",
            "reason": "Need approval for kb scope",
            "created_at": activity_payload["linked_runs"][0]["pending_approval"]["created_at"],
        }


@pytest.mark.asyncio
async def test_assistant_chat_selected_kbs_are_applied_when_model_omits_rag_kb_ids(tmp_path: Path) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    (kb_root / "ops.md").write_text(
        "# Incident Triage\n\n1. Assess impact.\n2. Classify severity.\n3. Notify responders.",
        encoding="utf-8",
    )

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="search kb without explicit kb ids",
                        tool_name="rag_search",
                        tool_arguments={
                            "query": "incident triage standard process",
                            "include_compiled_context": True,
                        },
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="answer",
                        final_output="triage answer",
                    ),
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )
    await app.state.ensure_initialized()
    await app.state.knowledge_service.register_knowledge_base(
        kb_id="kb-ops",
        tenant_id="tenant-a",
        name="Ops KB",
        root_path=str(kb_root),
        metadata={},
    )
    await app.state.knowledge_service.ingest("kb-ops")
    await app.state.run_service._repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["rag_search"],
            approval_required_tools=[],
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/assistant/sessions",
            json={
                "tenant_id": "tenant-a",
                "mode": "chat",
                "title": "Ops Chat",
            },
        )
        session_id = create_response.json()["session_id"]

        chat_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/chat",
            json={
                "tenant_id": "tenant-a",
                "content": "根据知识库回答 incident triage 的标准流程是什么？",
                "knowledge_base_ids": ["kb-ops"],
            },
        )

    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["status"] == "completed"
    assert chat_payload["assistant_message"]["content"] == "triage answer"

    repository = app.state.run_service._repository
    events = await repository.list_events(chat_payload["run_id"])
    tool_called_event = next(event for event in events if event.event_type == EventType.TOOL_CALLED)
    invocation = await repository.get_tool_invocation(tool_called_event.payload["invocation_id"])

    assert invocation is not None
    assert invocation.arguments == {
        "kb_ids": ["kb-ops"],
        "query": "incident triage standard process",
        "include_compiled_context": True,
    }


@pytest.mark.asyncio
async def test_assistant_chat_returns_failed_message_when_selected_kb_is_not_ready(tmp_path: Path) -> None:
    kb_root = tmp_path / "kb-empty"
    kb_root.mkdir()

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="search kb",
                        tool_name="rag_search",
                        tool_arguments={
                            "query": "incident triage standard process",
                            "include_compiled_context": True,
                        },
                    )
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )
    await app.state.ensure_initialized()
    await app.state.knowledge_service.register_knowledge_base(
        kb_id="kb-empty",
        tenant_id="tenant-a",
        name="Empty KB",
        root_path=str(kb_root),
        metadata={},
    )
    await app.state.knowledge_service.ingest("kb-empty")
    await app.state.run_service._repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["rag_search"],
            approval_required_tools=[],
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/assistant/sessions",
            json={
                "tenant_id": "tenant-a",
                "mode": "chat",
                "title": "Ops Chat",
            },
        )
        session_id = create_response.json()["session_id"]

        chat_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/chat",
            json={
                "tenant_id": "tenant-a",
                "content": "根据知识库回答 incident triage 的标准流程是什么？",
                "knowledge_base_ids": ["kb-empty"],
            },
        )

        assert chat_response.status_code == 200
        chat_payload = chat_response.json()
        assert chat_payload["status"] == "failed"
        assert "knowledge base" in chat_payload["assistant_message"]["content"]
        assert "kb-empty" in chat_payload["assistant_message"]["content"]
        assert chat_payload["assistant_message"]["structured_payload"]["run_status"] == "failed"

        activity_response = await client.get(
            f"/v1/assistant/sessions/{session_id}/activity",
            params={"tenant_id": "tenant-a"},
        )

    assert activity_response.status_code == 200
    activity_payload = activity_response.json()
    assert activity_payload["linked_runs"][0]["run_status"] == "failed"
