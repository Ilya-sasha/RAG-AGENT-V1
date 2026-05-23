# Agent Runtime Core M3 Tool Governance And Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add controlled tool execution, tenant-scoped policy enforcement, approval state transitions, and auditable governance events on top of the existing M1/M2 runtime.

**Architecture:** M3 extends the current event-driven runtime instead of bypassing it. Tool execution and approvals become first-class state transitions with durable tables, explicit gateway/service boundaries, checkpointed orchestration, and API contracts for operator actions.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite, httpx, pytest, pytest-asyncio

---

## File Structure

### Create

- `src/agent_runtime/tools/base.py`
  Tool execution protocol, request/response models, registry record types.
- `src/agent_runtime/tools/registry.py`
  In-memory/runtime-backed tool registry and lookup helpers.
- `src/agent_runtime/tools/gateway.py`
  Policy-aware tool gateway with approval interception and audit event emission.
- `src/agent_runtime/tenancy/policies.py`
  Tenant policy model and decision helpers for tool allowlists and approval rules.
- `src/agent_runtime/approvals/service.py`
  Approval creation, resolve, and resume coordination.
- `src/agent_runtime/api/routes/tools.py`
  Tool registry API endpoints.
- `src/agent_runtime/api/routes/tenants.py`
  Tenant policy API endpoints.
- `src/agent_runtime/api/routes/approvals.py`
  Approval query and resolve API endpoints.
- `tests/unit/test_tool_gateway.py`
  Unit tests for tool policy, approval interception, and audit behavior.
- `tests/integration/test_governance_repositories.py`
  Repository round-trip tests for tenants, tools, approvals, and tool invocations.
- `tests/integration/test_tool_approval_flow.py`
  End-to-end tests for tool calls, approval wait, approve/reject, and resume.

### Modify

- `src/agent_runtime/domain/enums.py`
  Extend run, agent, decision, event, approval, and tool invocation enums.
- `src/agent_runtime/domain/models.py`
  Add tenant, tool definition, tool invocation, approval request, and policy records.
- `src/agent_runtime/models/base.py`
  Extend model decision contract to express tool requests.
- `src/agent_runtime/models/scripted.py`
  Keep scripted client compatible with new decision kinds in tests.
- `src/agent_runtime/state/tables.py`
  Add ORM tables for tenants, tools, approval requests, and tool invocations.
- `src/agent_runtime/state/repositories.py`
  Add CRUD/state transitions for governance entities and auditable writes.
- `src/agent_runtime/runtime/orchestrator.py`
  Add tool-call branch, approval pause/resume branch, and post-tool observation merge.
- `src/agent_runtime/runtime/services.py`
  Wire tool gateway and approval service into run execution and startup recovery.
- `src/agent_runtime/runtime/resume.py`
  Extend resume coordination to recover waiting-for-approval and waiting-on-tool states.
- `src/agent_runtime/api/schemas.py`
  Add DTOs for tool registry, tenant policy, approval response, and action payloads.
- `src/agent_runtime/api/app.py`
  Wire new routers and governance services into application startup.

## Task 1: Add Governance Domain And Persistence Foundations

**Files:**
- Modify: `src/agent_runtime/domain/enums.py`
- Modify: `src/agent_runtime/domain/models.py`
- Modify: `src/agent_runtime/state/tables.py`
- Modify: `src/agent_runtime/state/repositories.py`
- Test: `tests/integration/test_governance_repositories.py`

- [ ] **Step 1: Write the failing repository test for tenant, tool, approval, and tool invocation records**

```python
# tests/integration/test_governance_repositories.py
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
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
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
```

- [ ] **Step 2: Run the new repository test to verify it fails**

Run: `pytest tests/integration/test_governance_repositories.py -v`
Expected: FAIL with missing enum/model/repository definitions for governance entities

- [ ] **Step 3: Add the minimal governance enums, records, tables, and repository methods**

```python
# src/agent_runtime/domain/enums.py
class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolInvocationStatus(StrEnum):
    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
```

```python
# src/agent_runtime/domain/models.py
class TenantPolicyRecord(BaseModel):
    tenant_id: str
    allowed_tools: list[str] = Field(default_factory=list)
    approval_required_tools: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolDefinitionRecord(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
```

```python
# src/agent_runtime/state/repositories.py
async def upsert_tenant_policy(self, policy: TenantPolicyRecord) -> None: ...
async def get_tenant_policy(self, tenant_id: str) -> TenantPolicyRecord | None: ...
async def upsert_tool_definition(self, tool: ToolDefinitionRecord) -> None: ...
async def get_tool_definition(self, tool_name: str) -> ToolDefinitionRecord | None: ...
async def create_approval_request(self, approval: ApprovalRequestRecord) -> None: ...
async def get_approval_request(self, approval_id: str) -> ApprovalRequestRecord | None: ...
async def create_tool_invocation(self, invocation: ToolInvocationRecord) -> None: ...
async def get_tool_invocation(self, invocation_id: str) -> ToolInvocationRecord | None: ...
```

- [ ] **Step 4: Run the governance repository test**

Run: `pytest tests/integration/test_governance_repositories.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/domain src/agent_runtime/state tests/integration/test_governance_repositories.py
git commit -m "feat: add governance state foundations"
```

## Task 2: Add Tenant Policy And Tool Registry APIs

**Files:**
- Create: `src/agent_runtime/api/routes/tools.py`
- Create: `src/agent_runtime/api/routes/tenants.py`
- Modify: `src/agent_runtime/api/schemas.py`
- Modify: `src/agent_runtime/api/app.py`
- Test: `tests/integration/test_tool_approval_flow.py`

- [ ] **Step 1: Write failing API assertions for tenant policy and tool registration**

```python
# tests/integration/test_tool_approval_flow.py
import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app


@pytest.mark.asyncio
async def test_tool_and_tenant_policy_endpoints_round_trip(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        tool_response = await client.post(
            "/v1/tools",
            json={
                "tool_name": "search-api",
                "description": "Search incidents",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                "requires_approval": False,
            },
        )
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={"allowed_tools": ["search-api"], "approval_required_tools": ["payment-api"]},
        )

        assert tool_response.status_code == 201
        assert policy_response.status_code == 200
        assert (await client.get("/v1/tools/search-api")).json()["tool_name"] == "search-api"
        assert (await client.get("/v1/tenants/tenant-a")).json()["allowed_tools"] == ["search-api"]
```

- [ ] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_tool_and_tenant_policy_endpoints_round_trip -v`
Expected: FAIL with missing `/v1/tools` and `/v1/tenants` routes

- [ ] **Step 3: Add DTOs and route handlers for tools and tenants**

```python
# src/agent_runtime/api/schemas.py
class ToolDefinitionRequest(BaseModel):
    tool_name: str
    description: str
    input_schema: dict
    requires_approval: bool = False


class TenantPolicyRequest(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list)
    approval_required_tools: list[str] = Field(default_factory=list)
```

```python
# src/agent_runtime/api/routes/tools.py
@router.post("", status_code=201, response_model=ToolDefinitionResponse)
async def register_tool(request: Request, payload: ToolDefinitionRequest) -> ToolDefinitionResponse: ...
```

```python
# src/agent_runtime/api/routes/tenants.py
@router.put("/{tenant_id}/policies", response_model=TenantPolicyResponse)
async def put_tenant_policy(request: Request, tenant_id: str, payload: TenantPolicyRequest) -> TenantPolicyResponse: ...
```

- [ ] **Step 4: Run the tenant/tool API test**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_tool_and_tenant_policy_endpoints_round_trip -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api tests/integration/test_tool_approval_flow.py
git commit -m "feat: add tenant policy and tool registry apis"
```

## Task 3: Add Tool Gateway And Approval Service Foundations

**Files:**
- Create: `src/agent_runtime/tools/base.py`
- Create: `src/agent_runtime/tools/registry.py`
- Create: `src/agent_runtime/tools/gateway.py`
- Create: `src/agent_runtime/approvals/service.py`
- Create: `src/agent_runtime/tenancy/policies.py`
- Test: `tests/unit/test_tool_gateway.py`

- [ ] **Step 1: Write failing unit tests for allowlist, approval interception, and completed tool execution**

```python
# tests/unit/test_tool_gateway.py
import pytest

from agent_runtime.tools.gateway import ToolGateway


@pytest.mark.asyncio
async def test_tool_gateway_blocks_disallowed_tool() -> None:
    gateway = ToolGateway(...)
    with pytest.raises(RuntimeError, match="tool not allowed"):
        await gateway.execute(...)
```

- [ ] **Step 2: Run the tool gateway tests to verify they fail**

Run: `pytest tests/unit/test_tool_gateway.py -v`
Expected: FAIL with missing tool gateway modules

- [ ] **Step 3: Implement minimal registry, policy helper, gateway, and approval service contracts**

```python
# src/agent_runtime/tools/base.py
class ToolExecutionRequest(BaseModel): ...
class ToolExecutionResult(BaseModel): ...
class ToolExecutor(Protocol):
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...
```

```python
# src/agent_runtime/tools/gateway.py
class ToolGateway:
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionOutcome: ...
```

- [ ] **Step 4: Run the tool gateway unit tests**

Run: `pytest tests/unit/test_tool_gateway.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/tools src/agent_runtime/approvals src/agent_runtime/tenancy tests/unit/test_tool_gateway.py
git commit -m "feat: add tool gateway and approval service foundations"
```

## Task 4: Extend The Orchestrator For Tool Calls And Approval Wait States

**Files:**
- Modify: `src/agent_runtime/domain/enums.py`
- Modify: `src/agent_runtime/domain/models.py`
- Modify: `src/agent_runtime/models/base.py`
- Modify: `src/agent_runtime/models/scripted.py`
- Modify: `src/agent_runtime/runtime/orchestrator.py`
- Modify: `src/agent_runtime/runtime/services.py`
- Modify: `src/agent_runtime/runtime/resume.py`
- Test: `tests/integration/test_tool_approval_flow.py`

- [ ] **Step 1: Add a failing integration test for approval-gated tool execution**

```python
@pytest.mark.asyncio
async def test_run_waits_for_approval_then_resumes_tool_execution(tmp_path) -> None:
    ...
    assert status_payload["status"] == "waiting_for_approval"
    assert replay_event_types[-1] == "approval.requested"
```

- [ ] **Step 2: Run the approval flow test to verify it fails**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_run_waits_for_approval_then_resumes_tool_execution -v`
Expected: FAIL because tool-call and approval states are not implemented

- [ ] **Step 3: Extend model decisions and orchestrator branches for `CALL_TOOL` and approval pauses**

```python
# src/agent_runtime/models/base.py
class ModelDecision(BaseModel):
    ...
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
```

```python
# src/agent_runtime/runtime/orchestrator.py
if decision.kind == DecisionKind.CALL_TOOL:
    outcome = await self._tool_gateway.execute(...)
    if outcome.requires_approval:
        ...
    else:
        ...
```

- [ ] **Step 4: Run the approval flow test**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_run_waits_for_approval_then_resumes_tool_execution -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/domain src/agent_runtime/models src/agent_runtime/runtime tests/integration/test_tool_approval_flow.py
git commit -m "feat: add tool-call and approval runtime flow"
```

## Task 5: Add Approval APIs, Resolution Flow, And Audit Coverage

**Files:**
- Create: `src/agent_runtime/api/routes/approvals.py`
- Modify: `src/agent_runtime/api/schemas.py`
- Modify: `src/agent_runtime/api/app.py`
- Modify: `src/agent_runtime/runtime/services.py`
- Test: `tests/integration/test_tool_approval_flow.py`

- [ ] **Step 1: Add failing API assertions for approval approve/reject flow**

```python
@pytest.mark.asyncio
async def test_approval_reject_fails_run_and_approve_resumes(tmp_path) -> None:
    ...
    approve_response = await client.post(f"/v1/approvals/{approval_id}/approve")
    reject_response = await client.post(f"/v1/approvals/{approval_id}/reject")
```

- [ ] **Step 2: Run the approval API tests to verify they fail**

Run: `pytest tests/integration/test_tool_approval_flow.py -v`
Expected: FAIL with missing approval routes and resolution flow

- [ ] **Step 3: Implement approval routes and audit events**

```python
# src/agent_runtime/api/routes/approvals.py
@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(...): ...

@router.post("/{approval_id}/approve", response_model=ActionAcceptedResponse)
async def approve_approval(...): ...

@router.post("/{approval_id}/reject", response_model=ActionAcceptedResponse)
async def reject_approval(...): ...
```

- [ ] **Step 4: Run the approval flow suite**

Run: `pytest tests/integration/test_tool_approval_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api src/agent_runtime/runtime tests/integration/test_tool_approval_flow.py
git commit -m "feat: add approval resolution apis and audit flow"
```

## Task 6: Final Governance Regression Pass

**Files:**
- Test: `tests/unit/test_tool_gateway.py`
- Test: `tests/integration/test_governance_repositories.py`
- Test: `tests/integration/test_tool_approval_flow.py`
- Test: `tests/integration/test_run_lifecycle.py`
- Test: `tests/integration/test_resume_flow.py`
- Test: `tests/integration/test_multi_agent_flow.py`

- [ ] **Step 1: Run the focused M3 suite**

Run: `pytest tests/unit/test_tool_gateway.py tests/integration/test_governance_repositories.py tests/integration/test_tool_approval_flow.py -v`
Expected: PASS

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/agent_runtime tests
git commit -m "test: verify m3 governance and approval flows"
```

## Self-Review Checklist

### Spec Coverage

- `tool gateway`
  Covered by Tasks 1, 3, 4, and 6.
- `tenant policy enforcement`
  Covered by Tasks 1, 2, 3, 4, and 6.
- `approval state machine`
  Covered by Tasks 1, 4, 5, and 6.
- `audit coverage`
  Covered by Tasks 1, 3, 4, 5, and 6 via invocation/approval persistence and event emission.

### Plan Cleanliness

- The plan intentionally limits tools to registered API-style adapters.
- The plan reuses the existing event and checkpoint architecture instead of adding a second orchestration path.
- No task depends on git execution because this workspace is not a git repository, but commit steps are preserved as plan placeholders for workflow parity.

### Type Consistency

- Governance records are named `TenantPolicyRecord`, `ToolDefinitionRecord`, `ToolInvocationRecord`, and `ApprovalRequestRecord`.
- Runtime governance services are named `ToolGateway` and `ApprovalService`.
- Decision expansion uses `DecisionKind.CALL_TOOL` plus existing `FINISH`/`DELEGATE`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-agent-runtime-core-m3-tool-governance-approval.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
