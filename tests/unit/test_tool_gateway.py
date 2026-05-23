import pytest

from agent_runtime.approvals.service import ApprovalService
from agent_runtime.domain.enums import ApprovalStatus, ToolInvocationStatus
from agent_runtime.domain.models import TenantPolicyRecord, ToolDefinitionRecord
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.tools.base import ToolExecutionRequest, ToolExecutionResult, ToolExecutor
from agent_runtime.tools.gateway import ToolGateway
from agent_runtime.tools.registry import ToolRegistry


class RecordingExecutor(ToolExecutor):
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.calls += 1
        return ToolExecutionResult(output=self.payload)


@pytest.mark.asyncio
async def test_tool_gateway_blocks_disallowed_tool(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)
    registry = ToolRegistry()
    approval_service = ApprovalService(repository)
    executor = RecordingExecutor({"status": "ok"})
    registry.register("payment-api", executor)

    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["search-api"],
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

    gateway = ToolGateway(repository, registry, approval_service)

    with pytest.raises(RuntimeError, match="tool not allowed"):
        await gateway.execute(
            ToolExecutionRequest(
                tenant_id="tenant-a",
                run_id="run-1",
                agent_id="agent-1",
                tool_name="payment-api",
                arguments={"amount": 10},
            )
        )

    assert executor.calls == 0


@pytest.mark.asyncio
async def test_tool_gateway_returns_approval_outcome_for_approval_required_tool(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)
    registry = ToolRegistry()
    approval_service = ApprovalService(repository)
    executor = RecordingExecutor({"status": "ok"})
    registry.register("payment-api", executor)

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

    gateway = ToolGateway(repository, registry, approval_service)
    outcome = await gateway.execute(
        ToolExecutionRequest(
            tenant_id="tenant-a",
            run_id="run-1",
            agent_id="agent-1",
            tool_name="payment-api",
            arguments={"amount": 10},
        )
    )

    assert outcome.requires_approval is True
    assert outcome.approval_id is not None
    assert outcome.result is None
    assert outcome.status == ToolInvocationStatus.WAITING_FOR_APPROVAL
    assert executor.calls == 0

    stored_approval = await repository.get_approval_request(outcome.approval_id)
    stored_invocation = await repository.get_tool_invocation(outcome.invocation_id)

    assert stored_approval is not None
    assert stored_approval.status == ApprovalStatus.PENDING
    assert stored_invocation is not None
    assert stored_invocation.status == ToolInvocationStatus.WAITING_FOR_APPROVAL


@pytest.mark.asyncio
async def test_tool_gateway_executes_allowed_tool_and_persists_audit(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)
    registry = ToolRegistry()
    approval_service = ApprovalService(repository)
    executor = RecordingExecutor({"matches": 3})
    registry.register("search-api", executor)

    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["search-api"],
            approval_required_tools=[],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="search-api",
            description="Searches incidents",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )

    gateway = ToolGateway(repository, registry, approval_service)
    outcome = await gateway.execute(
        ToolExecutionRequest(
            tenant_id="tenant-a",
            run_id="run-1",
            agent_id="agent-1",
            tool_name="search-api",
            arguments={"query": "database outage"},
        )
    )

    assert outcome.requires_approval is False
    assert outcome.status == ToolInvocationStatus.COMPLETED
    assert outcome.result == {"matches": 3}
    assert executor.calls == 1

    stored_invocation = await repository.get_tool_invocation(outcome.invocation_id)
    assert stored_invocation is not None
    assert stored_invocation.status == ToolInvocationStatus.COMPLETED
    assert stored_invocation.result == {"matches": 3}
