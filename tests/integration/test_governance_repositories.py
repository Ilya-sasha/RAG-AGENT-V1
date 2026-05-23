import pytest

from agent_runtime.domain.enums import ApprovalStatus, ToolInvocationStatus
from agent_runtime.domain.models import (
    ApprovalRequestRecord,
    TenantPolicyRecord,
    ToolDefinitionRecord,
    ToolInvocationRecord,
)
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_repository_persists_governance_entities(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)

    tenant = TenantPolicyRecord(
        tenant_id="tenant-a",
        allowed_tools=["search-api"],
        approval_required_tools=["payment-api"],
    )
    tool = ToolDefinitionRecord(
        tool_name="search-api",
        description="Searches an internal incident index",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        requires_approval=False,
    )
    approval = ApprovalRequestRecord(
        tenant_id="tenant-a",
        run_id="run-1",
        agent_id="agent-1",
        tool_name="payment-api",
        reason="high-risk action",
    )
    invocation = ToolInvocationRecord(
        tenant_id="tenant-a",
        run_id="run-1",
        agent_id="agent-1",
        tool_name="search-api",
        arguments={"query": "database outage"},
        status=ToolInvocationStatus.COMPLETED,
        result={"matches": 3},
    )

    await repository.upsert_tenant_policy(tenant)
    await repository.upsert_tool_definition(tool)
    await repository.create_approval_request(approval)
    await repository.create_tool_invocation(invocation)

    stored_tenant = await repository.get_tenant_policy("tenant-a")
    stored_tool = await repository.get_tool_definition("search-api")
    stored_approval = await repository.get_approval_request(approval.approval_id)
    stored_invocation = await repository.get_tool_invocation(invocation.invocation_id)

    assert stored_tenant is not None
    assert stored_tenant.allowed_tools == ["search-api"]

    assert stored_tool is not None
    assert stored_tool.tool_name == "search-api"

    assert stored_approval is not None
    assert stored_approval.status == ApprovalStatus.PENDING

    assert stored_invocation is not None
    assert stored_invocation.result == {"matches": 3}
