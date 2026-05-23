from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


class RecordingExecutor:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    async def execute(self, request) -> object:
        del request
        self.calls += 1
        from agent_runtime.tools.base import ToolExecutionResult

        return ToolExecutionResult(output=self.payload)


async def _wait_for_run_status(client, run_id: str, status: str) -> dict[str, object]:
    for _ in range(20):
        response = await client.get(f"/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    return payload


async def _wait_for_approval_id(repository, run_id: str) -> str:
    for _ in range(20):
        agents = await repository.list_agents(run_id)
        for agent in agents:
            latest_checkpoint = await repository.get_latest_checkpoint(run_id, agent.agent_id)
            if latest_checkpoint is not None:
                approval_id = latest_checkpoint.payload.get("approval_id")
                if approval_id is not None:
                    return approval_id

        events = await repository.list_events(run_id)
        for event in reversed(events):
            approval_id = event.payload.get("approval_id")
            if approval_id is not None:
                return approval_id

        await asyncio.sleep(0.05)

    raise AssertionError(f"approval_id was not recorded for run {run_id}")


@pytest.mark.asyncio
async def test_workflow_template_create_publish_and_launch(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind="finish",
                        summary="done",
                        final_output="triaged",
                    )
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    kb_root = tmp_path / "kb"
    kb_root.mkdir()

    async with app_client_context(app) as client:
        kb_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-ops",
                "tenant_id": "tenant-a",
                "name": "Ops KB",
                "root_path": str(kb_root),
            },
        )
        assert kb_response.status_code == 201

        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-triage",
                "tenant_id": "tenant-a",
                "name": "Incident Triage",
                "description": "Triage incidents with RAG lookup",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Triage incident {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": ["rag_search"],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": ["kb-ops"],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 8,
                        "timeout_seconds": 600,
                        "tags": ["ops"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                "created_by": "operator-a",
            },
        )

        assert create_response.status_code == 201
        assert create_response.json() == {
            "template_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triage incidents with RAG lookup",
            "status": "draft",
            "latest_version": 1,
        }

        list_response = await client.get("/v1/workflow-templates", params={"tenant_id": "tenant-a"})
        assert list_response.status_code == 200
        assert list_response.json() == [create_response.json()]

        publish_response = await client.post(
            "/v1/workflow-templates/wf-triage/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )

        assert publish_response.status_code == 200
        assert publish_response.json() == {
            "template_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triage incidents with RAG lookup",
            "status": "published",
            "latest_version": 1,
        }

        launch_response = await client.post(
            "/v1/workflow-templates/wf-triage/launch",
            json={
                "tenant_id": "tenant-a",
                "version": 1,
                "input": {"ticket_id": "INC-42"},
                "metadata": {"requested_by": "operator-a"},
            },
        )

        assert launch_response.status_code == 201
        launch_payload = launch_response.json()
        assert launch_payload["tenant_id"] == "tenant-a"
        assert launch_payload["objective"] == "Triage incident INC-42"
        assert launch_payload["status"] == "created"
        assert launch_payload["result"] is None
        assert launch_payload["error"] is None
        assert launch_payload["workflow_template"] == {
            "template_id": "wf-triage",
            "version": 1,
            "name": "Incident Triage",
        }

        run_id = launch_payload["run_id"]
        stored_run_link = await app.state.run_service._workflow_repository.get_run_link(run_id)
        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        assert payload["status"] == "completed"
        assert payload["result"] == "triaged"
        assert stored_run_link is not None
        assert stored_run_link.launch_metadata == {"requested_by": "operator-a"}


@pytest.mark.asyncio
async def test_workflow_template_create_rejects_duplicate_template_id(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    payload = {
        "template_id": "wf-triage",
        "tenant_id": "tenant-a",
        "name": "Incident Triage",
        "description": "Triage incidents with RAG lookup",
        "definition": {
            "entrypoint": {
                "objective_template": "Triage incident {ticket_id}",
                "result_contract": "string",
            },
            "agents": {
                "allowed_worker_roles": ["researcher"],
                "max_worker_count": 1,
            },
            "tools": {
                "allowed_tools": [],
                "approval_required_tools": [],
            },
            "knowledge": {
                "default_kb_ids": [],
                "allow_kb_override": False,
            },
            "runtime": {
                "max_turns": 8,
                "timeout_seconds": 600,
                "tags": ["ops"],
            },
            "launch_policy": {
                "allow_input_objective_override": False,
                "require_published_version": True,
            },
        },
        "input_schema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
        "created_by": "operator-a",
    }

    async with app_client_context(app) as client:
        first_response = await client.post("/v1/workflow-templates", json=payload)
        assert first_response.status_code == 201

        duplicate_response = await client.post("/v1/workflow-templates", json=payload)

        assert duplicate_response.status_code == 409
        assert duplicate_response.json() == {
            "detail": "workflow template already exists: tenant-a/wf-triage"
        }


@pytest.mark.asyncio
async def test_workflow_template_launch_rejects_missing_required_input(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": [],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-triage",
                "tenant_id": "tenant-a",
                "name": "Incident Triage",
                "description": "Triage incidents with RAG lookup",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Triage incident {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": [],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": [],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 8,
                        "timeout_seconds": 600,
                        "tags": ["ops"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": [],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        publish_response = await client.post(
            "/v1/workflow-templates/wf-triage/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        launch_response = await client.post(
            "/v1/workflow-templates/wf-triage/launch",
            json={
                "tenant_id": "tenant-a",
                "version": 1,
                "input": {},
            },
        )

        assert launch_response.status_code == 400
        assert launch_response.json() == {
            "detail": "workflow template launch input missing required fields: ticket_id"
        }


@pytest.mark.asyncio
async def test_workflow_template_routes_are_tenant_scoped_for_list_and_launch(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    payload = {
        "template_id": "wf-triage",
        "tenant_id": "tenant-a",
        "name": "Incident Triage",
        "description": "Triage incidents with RAG lookup",
        "definition": {
            "entrypoint": {
                "objective_template": "Triage incident {ticket_id}",
                "result_contract": "string",
            },
            "agents": {
                "allowed_worker_roles": ["researcher"],
                "max_worker_count": 1,
            },
            "tools": {
                "allowed_tools": [],
                "approval_required_tools": [],
            },
            "knowledge": {
                "default_kb_ids": [],
                "allow_kb_override": False,
            },
            "runtime": {
                "max_turns": 8,
                "timeout_seconds": 600,
                "tags": ["ops"],
            },
            "launch_policy": {
                "allow_input_objective_override": False,
                "require_published_version": True,
            },
        },
        "input_schema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
        "created_by": "operator-a",
    }

    async with app_client_context(app) as client:
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": [],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post("/v1/workflow-templates", json=payload)
        assert create_response.status_code == 201

        publish_response = await client.post(
            "/v1/workflow-templates/wf-triage/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        foreign_list_response = await client.get("/v1/workflow-templates", params={"tenant_id": "tenant-b"})
        assert foreign_list_response.status_code == 200
        assert foreign_list_response.json() == []

        foreign_launch_response = await client.post(
            "/v1/workflow-templates/wf-triage/launch",
            json={
                "tenant_id": "tenant-b",
                "version": 1,
                "input": {"ticket_id": "INC-42"},
            },
        )
        assert foreign_launch_response.status_code == 404
        assert foreign_launch_response.json() == {"detail": "workflow template not found: wf-triage"}


@pytest.mark.asyncio
async def test_workflow_template_publish_rejects_unknown_kb_binding(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-triage",
                "tenant_id": "tenant-a",
                "name": "Incident Triage",
                "description": "Triage incidents with RAG lookup",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Triage incident {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": ["rag_search"],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": ["kb-missing"],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 8,
                        "timeout_seconds": 600,
                        "tags": ["ops"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        publish_response = await client.post(
            "/v1/workflow-templates/wf-triage/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 400
        assert publish_response.json() == {"detail": "unknown knowledge base: kb-missing"}


@pytest.mark.asyncio
async def test_workflow_template_launch_preserves_approval_pause_and_resume(tmp_path: Path) -> None:
    from agent_runtime.tools.registry import ToolRegistry

    registry = ToolRegistry()
    executor = RecordingExecutor({"status": "ok"})
    registry.register("payment-api", executor)

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind="call_tool",
                        summary="call payment tool",
                        tool_name="payment-api",
                        tool_arguments={"amount": 10},
                    ),
                    ModelDecision(
                        kind="finish",
                        summary="payment submitted",
                        final_output="payment submitted",
                    ),
                ]
            }
        ),
        tool_registry=registry,
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        tool_response = await client.post(
            "/v1/tools",
            json={
                "tool_name": "payment-api",
                "description": "Submits a payment",
                "input_schema": {"type": "object"},
                "requires_approval": False,
            },
        )
        assert tool_response.status_code == 201

        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["payment-api"],
                "approval_required_tools": ["payment-api"],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-pay",
                "tenant_id": "tenant-a",
                "name": "Payment Workflow",
                "description": "Launches approval-gated payment",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Submit payment for {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": [],
                        "max_worker_count": 0,
                    },
                    "tools": {
                        "allowed_tools": ["payment-api"],
                        "approval_required_tools": ["payment-api"],
                    },
                    "knowledge": {
                        "default_kb_ids": [],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 4,
                        "timeout_seconds": 300,
                        "tags": ["payments"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        publish_response = await client.post(
            "/v1/workflow-templates/wf-pay/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        launch_response = await client.post(
            "/v1/workflow-templates/wf-pay/launch",
            json={
                "tenant_id": "tenant-a",
                "input": {"ticket_id": "INC-7"},
            },
        )
        assert launch_response.status_code == 201
        run_id = launch_response.json()["run_id"]

        waiting_payload = await _wait_for_run_status(client, run_id, "waiting_for_approval")
        assert waiting_payload["status"] == "waiting_for_approval"

        repository = app.state.run_service._repository
        approval_id = await _wait_for_approval_id(repository, run_id)

        approve_response = await client.post(
            f"/v1/approvals/{approval_id}/approve",
            json={"resolution_note": "approved by api"},
        )
        assert approve_response.status_code == 200

        completed_payload = await _wait_for_run_status(client, run_id, "completed")
        assert completed_payload["status"] == "completed"
        assert completed_payload["result"] == "payment submitted"
        assert executor.calls == 1


@pytest.mark.asyncio
async def test_workflow_template_launch_preserves_rag_search_path_with_default_kb_binding(tmp_path: Path) -> None:
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
                        kind="call_tool",
                        summary="search the knowledge base",
                        tool_name="rag_search",
                        tool_arguments={
                            "kb_ids": ["kb-ops"],
                            "query": "Alpha retrieval text",
                            "top_k": 2,
                            "include_compiled_context": True,
                        },
                    ),
                    ModelDecision(
                        kind="finish",
                        summary="done",
                        final_output="retrieval complete",
                    ),
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )
    await app.state.ensure_initialized()

    async with app_client_context(app) as client:
        kb_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-ops",
                "tenant_id": "tenant-a",
                "name": "Ops KB",
                "root_path": str(kb_root),
            },
        )
        assert kb_response.status_code == 201

        ingest_response = await client.post("/internal/knowledge-bases/kb-ops/ingest")
        assert ingest_response.status_code == 202

        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-rag",
                "tenant_id": "tenant-a",
                "name": "RAG Workflow",
                "description": "Runs retrieval through rag_search",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Search docs for {query}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": ["rag_search"],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": ["kb-ops"],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 6,
                        "timeout_seconds": 300,
                        "tags": ["rag"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        publish_response = await client.post(
            "/v1/workflow-templates/wf-rag/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        launch_response = await client.post(
            "/v1/workflow-templates/wf-rag/launch",
            json={
                "tenant_id": "tenant-a",
                "input": {"query": "Alpha retrieval text"},
            },
        )
        assert launch_response.status_code == 201
        run_id = launch_response.json()["run_id"]

        completed_payload = await _wait_for_run_status(client, run_id, "completed")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")

    repository = app.state.run_service._repository
    events = await repository.list_events(run_id)
    tool_called_event = next(event for event in events if event.event_type.value == "tool.called")
    invocation = await repository.get_tool_invocation(tool_called_event.payload["invocation_id"])

    assert completed_payload["status"] == "completed"
    assert completed_payload["result"] == "retrieval complete"
    assert "tool.called" in [event["event_type"] for event in replay_response.json()["events"]]
    assert invocation is not None
    assert invocation.tool_name == "rag_search"
    assert invocation.arguments == {
        "kb_ids": ["kb-ops"],
        "query": "Alpha retrieval text",
        "top_k": 2,
        "include_compiled_context": True,
    }
    assert invocation.result is not None
    assert invocation.result["query_metadata"] == {"kb_ids": ["kb-ops"], "top_k": 2}


@pytest.mark.asyncio
async def test_workflow_template_launch_hydrates_rag_search_kb_ids_from_default_binding(
    tmp_path: Path,
) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    (kb_root / "guide.md").write_text("# Intro\n\nAlpha retrieval text", encoding="utf-8")

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind="call_tool",
                        summary="search the knowledge base",
                        tool_name="rag_search",
                        tool_arguments={
                            "query": "Alpha retrieval text",
                            "top_k": 2,
                            "include_compiled_context": True,
                        },
                    ),
                    ModelDecision(
                        kind="finish",
                        summary="done",
                        final_output="retrieval complete",
                    ),
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )
    await app.state.ensure_initialized()

    async with app_client_context(app) as client:
        kb_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-ops",
                "tenant_id": "tenant-a",
                "name": "Ops KB",
                "root_path": str(kb_root),
            },
        )
        assert kb_response.status_code == 201

        ingest_response = await client.post("/internal/knowledge-bases/kb-ops/ingest")
        assert ingest_response.status_code == 202

        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-rag-default-kb",
                "tenant_id": "tenant-a",
                "name": "RAG Workflow",
                "description": "Hydrates kb_ids from workflow default knowledge bindings",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Search docs for {query}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": ["rag_search"],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": ["kb-ops"],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 6,
                        "timeout_seconds": 300,
                        "tags": ["rag"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        publish_response = await client.post(
            "/v1/workflow-templates/wf-rag-default-kb/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        launch_response = await client.post(
            "/v1/workflow-templates/wf-rag-default-kb/launch",
            json={
                "tenant_id": "tenant-a",
                "input": {"query": "Alpha retrieval text"},
            },
        )
        assert launch_response.status_code == 201
        run_id = launch_response.json()["run_id"]

        completed_payload = await _wait_for_run_status(client, run_id, "completed")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")

    repository = app.state.run_service._repository
    events = await repository.list_events(run_id)
    tool_called_event = next(event for event in events if event.event_type.value == "tool.called")
    invocation = await repository.get_tool_invocation(tool_called_event.payload["invocation_id"])

    assert completed_payload["status"] == "completed"
    assert completed_payload["result"] == "retrieval complete"
    assert "tool.called" in [event["event_type"] for event in replay_response.json()["events"]]
    assert invocation is not None
    assert invocation.tool_name == "rag_search"
    assert invocation.arguments == {
        "kb_ids": ["kb-ops"],
        "query": "Alpha retrieval text",
        "top_k": 2,
        "include_compiled_context": True,
    }
    assert invocation.result is not None
    assert invocation.result["query_metadata"] == {"kb_ids": ["kb-ops"], "top_k": 2}


@pytest.mark.asyncio
async def test_workflow_template_launch_replaces_placeholder_kb_ids_with_default_binding(
    tmp_path: Path,
) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    (kb_root / "guide.md").write_text("# Intro\n\nAlpha retrieval text", encoding="utf-8")

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind="call_tool",
                        summary="search the knowledge base",
                        tool_name="rag_search",
                        tool_arguments={
                            "kb_ids": ["all"],
                            "query": "Alpha retrieval text",
                            "top_k": 2,
                            "include_compiled_context": True,
                        },
                    ),
                    ModelDecision(
                        kind="finish",
                        summary="done",
                        final_output="retrieval complete",
                    ),
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )
    await app.state.ensure_initialized()

    async with app_client_context(app) as client:
        kb_response = await client.post(
            "/internal/knowledge-bases",
            json={
                "kb_id": "kb-ops",
                "tenant_id": "tenant-a",
                "name": "Ops KB",
                "root_path": str(kb_root),
            },
        )
        assert kb_response.status_code == 201

        ingest_response = await client.post("/internal/knowledge-bases/kb-ops/ingest")
        assert ingest_response.status_code == 202

        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-rag-placeholder-kb",
                "tenant_id": "tenant-a",
                "name": "RAG Workflow",
                "description": "Replaces placeholder kb_ids with workflow defaults",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Search docs for {query}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": ["rag_search"],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": ["kb-ops"],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 6,
                        "timeout_seconds": 300,
                        "tags": ["rag"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        publish_response = await client.post(
            "/v1/workflow-templates/wf-rag-placeholder-kb/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        launch_response = await client.post(
            "/v1/workflow-templates/wf-rag-placeholder-kb/launch",
            json={
                "tenant_id": "tenant-a",
                "input": {"query": "Alpha retrieval text"},
            },
        )
        assert launch_response.status_code == 201
        run_id = launch_response.json()["run_id"]

        completed_payload = await _wait_for_run_status(client, run_id, "completed")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")

    repository = app.state.run_service._repository
    events = await repository.list_events(run_id)
    tool_called_event = next(event for event in events if event.event_type.value == "tool.called")
    invocation = await repository.get_tool_invocation(tool_called_event.payload["invocation_id"])

    assert completed_payload["status"] == "completed"
    assert completed_payload["result"] == "retrieval complete"
    assert "tool.called" in [event["event_type"] for event in replay_response.json()["events"]]
    assert invocation is not None
    assert invocation.tool_name == "rag_search"
    assert invocation.arguments == {
        "kb_ids": ["kb-ops"],
        "query": "Alpha retrieval text",
        "top_k": 2,
        "include_compiled_context": True,
    }
    assert invocation.result is not None
    assert invocation.result["query_metadata"] == {"kb_ids": ["kb-ops"], "top_k": 2}


@pytest.mark.asyncio
async def test_workflow_template_compatibility_routes_cover_lifecycle_detail_update_delete_and_archive(
    tmp_path: Path,
) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": [],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflow-templates",
            json={
                "template_id": "wf-compat",
                "tenant_id": "tenant-a",
                "name": "Compatibility Workflow",
                "description": "Exercises legacy route family against the v2 lifecycle service",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Handle incident {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": [],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": [],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 8,
                        "timeout_seconds": 600,
                        "tags": ["compat"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        detail_response = await client.get(
            "/v1/workflow-templates/wf-compat",
            params={"tenant_id": "tenant-a"},
        )
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload == {
            "template_id": "wf-compat",
            "tenant_id": "tenant-a",
            "name": "Compatibility Workflow",
            "description": "Exercises legacy route family against the v2 lifecycle service",
            "status": "draft",
            "latest_version": 1,
            "latest_published_version": None,
            "created_at": detail_payload["created_at"],
            "updated_at": detail_payload["updated_at"],
            "archived_at": None,
            "latest_draft": {
                "version": 1,
                "definition": {
                    "entrypoint": {
                        "objective_template": "Handle incident {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": [],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": [],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 8,
                        "timeout_seconds": 600,
                        "tags": ["compat"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                "source_version": None,
                "is_published": False,
                "created_by": "operator-a",
            },
            "latest_published": None,
            "version_summaries": [
                {
                    "version": 1,
                    "status": "draft",
                    "is_published": False,
                    "source_version": None,
                    "created_by": "operator-a",
                }
            ],
        }
        assert detail_payload["created_at"] is not None
        assert detail_payload["updated_at"] is not None

        create_version_response = await client.post(
            "/v1/workflow-templates/wf-compat/versions",
            json={"tenant_id": "tenant-a", "created_by": "operator-b"},
        )
        assert create_version_response.status_code == 201
        assert create_version_response.json() == {
            "version": 2,
            "definition": {
                "entrypoint": {
                    "objective_template": "Handle incident {ticket_id}",
                    "result_contract": "string",
                },
                "agents": {
                    "allowed_worker_roles": ["researcher"],
                    "max_worker_count": 1,
                },
                "tools": {
                    "allowed_tools": [],
                    "approval_required_tools": [],
                },
                "knowledge": {
                    "default_kb_ids": [],
                    "allow_kb_override": False,
                },
                "runtime": {
                    "max_turns": 8,
                    "timeout_seconds": 600,
                    "tags": ["compat"],
                },
                "launch_policy": {
                    "allow_input_objective_override": False,
                    "require_published_version": True,
                },
            },
            "input_schema": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
            },
            "source_version": 1,
            "is_published": False,
            "created_by": "operator-b",
        }

        update_response = await client.put(
            "/v1/workflow-templates/wf-compat/versions/2",
            json={
                "tenant_id": "tenant-a",
                "definition": {
                    "entrypoint": {
                        "objective_template": "Handle incident {ticket_id}",
                        "result_contract": "string",
                    },
                    "agents": {
                        "allowed_worker_roles": ["researcher"],
                        "max_worker_count": 1,
                    },
                    "tools": {
                        "allowed_tools": [],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": [],
                        "allow_kb_override": False,
                    },
                    "runtime": {
                        "max_turns": 3,
                        "timeout_seconds": 120,
                        "tags": ["compat", "updated"],
                    },
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                    "required": ["ticket_id", "severity"],
                },
            },
        )
        assert update_response.status_code == 200
        assert update_response.json() == {
            "version": 2,
            "definition": {
                "entrypoint": {
                    "objective_template": "Handle incident {ticket_id}",
                    "result_contract": "string",
                },
                "agents": {
                    "allowed_worker_roles": ["researcher"],
                    "max_worker_count": 1,
                },
                "tools": {
                    "allowed_tools": [],
                    "approval_required_tools": [],
                },
                "knowledge": {
                    "default_kb_ids": [],
                    "allow_kb_override": False,
                },
                "runtime": {
                    "max_turns": 3,
                    "timeout_seconds": 120,
                    "tags": ["compat", "updated"],
                },
                "launch_policy": {
                    "allow_input_objective_override": False,
                    "require_published_version": True,
                },
            },
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "severity": {"type": "string"},
                },
                "required": ["ticket_id", "severity"],
            },
            "source_version": 1,
            "is_published": False,
            "created_by": "operator-b",
        }

        publish_response = await client.post(
            "/v1/workflow-templates/wf-compat/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        delete_response = await client.delete(
            "/v1/workflow-templates/wf-compat/versions/2",
            params={"tenant_id": "tenant-a"},
        )
        assert delete_response.status_code == 204
        assert delete_response.content == b""

        archive_response = await client.post(
            "/v1/workflow-templates/wf-compat/archive",
            json={"tenant_id": "tenant-a"},
        )
        assert archive_response.status_code == 200
        archive_payload = archive_response.json()
        assert archive_payload["template_id"] == "wf-compat"
        assert archive_payload["tenant_id"] == "tenant-a"
        assert archive_payload["status"] == "archived"
        assert archive_payload["latest_version"] == 1
        assert archive_payload["latest_published_version"] == 1
        assert archive_payload["archived_at"] is not None
