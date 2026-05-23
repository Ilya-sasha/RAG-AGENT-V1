import asyncio

import pytest
from httpx import AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import AgentStatus, ApprovalStatus, DecisionKind, RunStatus, ToolInvocationStatus
from agent_runtime.domain.models import TenantPolicyRecord, ToolDefinitionRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.testing.faults import FaultPoint, FaultRule, RuleBasedFaultInjector
from agent_runtime.tools.base import ToolExecutionRequest, ToolExecutionResult, ToolExecutor
from agent_runtime.tools.registry import ToolRegistry
from tests.conftest import app_client_context


class RecordingExecutor(ToolExecutor):
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        return ToolExecutionResult(output=self.payload)


async def _wait_for_run_status(client: AsyncClient, run_id: str, status: str) -> dict[str, object]:
    for _ in range(20):
        response = await client.get(f"/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    return payload


@pytest.mark.asyncio
async def test_tool_and_tenant_policy_endpoints_round_trip(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        tool_response = await client.post(
            "/v1/tools",
            json={
                "tool_name": "search-api",
                "description": "Search incidents",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "requires_approval": False,
            },
        )
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["search-api"],
                "approval_required_tools": ["payment-api"],
            },
        )

        assert tool_response.status_code == 201
        assert policy_response.status_code == 200
        assert (await client.get("/v1/tools/search-api")).json()["tool_name"] == "search-api"
        assert (await client.get("/v1/tenants/tenant-a")).json()["allowed_tools"] == ["search-api"]


@pytest.mark.asyncio
async def test_run_waits_for_approval_then_resumes_tool_execution(tmp_path) -> None:
    registry = ToolRegistry()
    executor = RecordingExecutor({"status": "ok"})
    registry.register("payment-api", executor)

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="call payment tool",
                        tool_name="payment-api",
                        tool_arguments={"amount": 10},
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="payment submitted",
                        final_output="payment submitted",
                    ),
                ]
            }
        ),
        tool_registry=registry,
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["payment-api"],
            approval_required_tools=["payment-api"],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="payment-api",
            description="Submits a payment",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )
    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "submit payment"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            status_payload = status_response.json()
            if status_payload["status"] == "waiting_for_approval":
                break
            await asyncio.sleep(0.05)

        agents = await repository.list_agents(run_id)
        latest_checkpoint = await repository.get_latest_checkpoint(run_id, agents[0].agent_id)
        assert latest_checkpoint is not None
        approval_id = latest_checkpoint.payload["approval_id"]
        invocation_id = latest_checkpoint.payload["invocation_id"]

        await repository.update_approval_request(
            approval_id,
            status=ApprovalStatus.APPROVED,
            resolution_note="approved by integration test",
        )
        await repository.update_run_status(run_id, RunStatus.RUNNING)
        await repository.update_agent_state(
            agents[0].agent_id,
            status=AgentStatus.WAITING_ON_TOOL,
        )

        resume_response = await client.post(f"/v1/runs/{run_id}/resume")
        metrics_response = await client.get("/metrics")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        replay_event_types = [event["event_type"] for event in replay_response.json()["events"]]
        stored_run = await repository.get_run(run_id)
        stored_agent = await repository.get_agent(agents[0].agent_id)
        stored_invocation = await repository.get_tool_invocation(invocation_id)
        stored_approval = await repository.get_approval_request(approval_id)

        assert status_payload["status"] == "waiting_for_approval"
        assert resume_response.status_code == 200
        assert "runtime_tool_calls_total" in metrics_response.text
        assert 'tool_name="payment-api"' in metrics_response.text
        assert replay_event_types[-1] == "run.completed"
        assert stored_run is not None
        assert stored_run.status == RunStatus.COMPLETED
        assert stored_run.result == "payment submitted"
        assert stored_agent is not None
        assert stored_agent.status == AgentStatus.COMPLETED
        assert "payment-api:{'status': 'ok'}" in stored_agent.observations
        assert stored_invocation is not None
        assert stored_invocation.status == ToolInvocationStatus.COMPLETED
        assert stored_invocation.result == {"status": "ok"}
        assert stored_approval is not None
        assert stored_approval.status == ApprovalStatus.APPROVED
        assert executor.calls == 1


@pytest.mark.asyncio
async def test_approval_approve_endpoint_resolves_request_and_resumes_run(tmp_path) -> None:
    registry = ToolRegistry()
    executor = RecordingExecutor({"status": "ok"})
    registry.register("payment-api", executor)

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="call payment tool",
                        tool_name="payment-api",
                        tool_arguments={"amount": 10},
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="payment submitted",
                        final_output="payment submitted",
                    ),
                ]
            }
        ),
        tool_registry=registry,
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["payment-api"],
            approval_required_tools=["payment-api"],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="payment-api",
            description="Submits a payment",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "submit payment"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        waiting_payload = await _wait_for_run_status(client, run_id, "waiting_for_approval")
        agents = await repository.list_agents(run_id)
        latest_checkpoint = await repository.get_latest_checkpoint(run_id, agents[0].agent_id)
        assert latest_checkpoint is not None
        approval_id = latest_checkpoint.payload["approval_id"]
        invocation_id = latest_checkpoint.payload["invocation_id"]

        pending_response = await client.get(f"/v1/approvals/{approval_id}")
        approve_response = await client.post(
            f"/v1/approvals/{approval_id}/approve",
            json={"resolution_note": "approved by api"},
        )
        approval_response = await client.get(f"/v1/approvals/{approval_id}")
        metrics_response = await client.get("/metrics")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        replay_event_types = [event["event_type"] for event in replay_response.json()["events"]]
        stored_run = await repository.get_run(run_id)
        stored_invocation = await repository.get_tool_invocation(invocation_id)

        assert waiting_payload["status"] == "waiting_for_approval"
        assert pending_response.status_code == 200
        assert pending_response.json()["status"] == "pending"
        assert approve_response.status_code == 200
        assert approval_response.status_code == 200
        assert approval_response.json()["status"] == "approved"
        assert approval_response.json()["resolution_note"] == "approved by api"
        assert "runtime_approval_resolutions_total" in metrics_response.text
        assert 'status="approved"' in metrics_response.text
        assert "approval.resolved" in replay_event_types
        assert replay_event_types[-1] == "run.completed"
        assert stored_run is not None
        assert stored_run.status == RunStatus.COMPLETED
        assert stored_run.result == "payment submitted"
        assert stored_invocation is not None
        assert stored_invocation.status == ToolInvocationStatus.COMPLETED
        assert executor.calls == 1


@pytest.mark.asyncio
async def test_approval_reject_endpoint_fails_waiting_run(tmp_path) -> None:
    registry = ToolRegistry()
    executor = RecordingExecutor({"status": "ok"})
    registry.register("payment-api", executor)

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="call payment tool",
                        tool_name="payment-api",
                        tool_arguments={"amount": 10},
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="payment submitted",
                        final_output="payment submitted",
                    ),
                ]
            }
        ),
        tool_registry=registry,
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["payment-api"],
            approval_required_tools=["payment-api"],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="payment-api",
            description="Submits a payment",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "submit payment"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        waiting_payload = await _wait_for_run_status(client, run_id, "waiting_for_approval")
        agents = await repository.list_agents(run_id)
        latest_checkpoint = await repository.get_latest_checkpoint(run_id, agents[0].agent_id)
        assert latest_checkpoint is not None
        approval_id = latest_checkpoint.payload["approval_id"]
        invocation_id = latest_checkpoint.payload["invocation_id"]

        reject_response = await client.post(
            f"/v1/approvals/{approval_id}/reject",
            json={"resolution_note": "rejected by api"},
        )
        approval_response = await client.get(f"/v1/approvals/{approval_id}")
        metrics_response = await client.get("/metrics")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        replay_event_types = [event["event_type"] for event in replay_response.json()["events"]]
        stored_run = await repository.get_run(run_id)
        stored_agent = await repository.get_agent(agents[0].agent_id)
        stored_invocation = await repository.get_tool_invocation(invocation_id)

        assert waiting_payload["status"] == "waiting_for_approval"
        assert reject_response.status_code == 200
        assert approval_response.status_code == 200
        assert approval_response.json()["status"] == "rejected"
        assert approval_response.json()["resolution_note"] == "rejected by api"
        assert "runtime_approval_resolutions_total" in metrics_response.text
        assert 'status="rejected"' in metrics_response.text
        assert "approval.resolved" in replay_event_types
        assert replay_event_types[-1] == "run.failed"
        assert stored_run is not None
        assert stored_run.status == RunStatus.FAILED
        assert stored_run.error == "approval rejected for tool: payment-api"
        assert stored_agent is not None
        assert stored_agent.status == AgentStatus.FAILED
        assert stored_invocation is not None
        assert stored_invocation.status == ToolInvocationStatus.WAITING_FOR_APPROVAL
        assert executor.calls == 0


@pytest.mark.asyncio
async def test_injected_tool_execution_failure_marks_run_failed(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register("payment-api", RecordingExecutor({"status": "ok"}))

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="call payment tool",
                        tool_name="payment-api",
                        tool_arguments={"amount": 10},
                    )
                ]
            }
        ),
        tool_registry=registry,
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.TOOL_BEFORE_EXECUTE,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected tool failure"),
                )
            ]
        ),
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["payment-api"],
            approval_required_tools=[],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="payment-api",
            description="Submits a payment",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "submit payment"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "failed":
                break
            await asyncio.sleep(0.05)

        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        event_types = [event["event_type"] for event in replay_response.json()["events"]]

    assert payload["status"] == "failed"
    assert "injected tool failure" in payload["error"]
    assert event_types[-1] == "run.failed"


@pytest.mark.asyncio
async def test_injected_tool_resume_failure_marks_run_failed(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register("payment-api", RecordingExecutor({"status": "ok"}))

    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.CALL_TOOL,
                        summary="call payment tool",
                        tool_name="payment-api",
                        tool_arguments={"amount": 10},
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="payment submitted",
                        final_output="payment submitted",
                    ),
                ]
            }
        ),
        tool_registry=registry,
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.TOOL_BEFORE_RESUME,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected tool resume failure"),
                )
            ]
        ),
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["payment-api"],
            approval_required_tools=["payment-api"],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="payment-api",
            description="Submits a payment",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "submit payment"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        waiting_payload = await _wait_for_run_status(client, run_id, "waiting_for_approval")
        assert waiting_payload["status"] == "waiting_for_approval"

        agents = await repository.list_agents(run_id)
        latest_checkpoint = await repository.get_latest_checkpoint(run_id, agents[0].agent_id)
        assert latest_checkpoint is not None
        approval_id = latest_checkpoint.payload["approval_id"]

        approve_response = await client.post(
            f"/v1/approvals/{approval_id}/approve",
            json={"resolution_note": "approved by api"},
        )
        assert approve_response.status_code == 200

        failed_payload = await _wait_for_run_status(client, run_id, "failed")
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        event_types = [event["event_type"] for event in replay_response.json()["events"]]

    assert failed_payload["status"] == "failed"
    assert "injected tool resume failure" in failed_payload["error"]
    assert event_types[-1] == "run.failed"
