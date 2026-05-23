# Agent Runtime Workflow V2 Tenant Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an API-first, tenant-scoped workflow observability surface that lists workflow-started runs with filters and exposes a single-run observation detail view for platform and operations users.

**Architecture:** Keep the existing workflow launch and runtime write path unchanged. Add one new workflow-observability read layer composed of repository query helpers, a dedicated `WorkflowObservabilityService`, and a new `/v1/workflow-runs` route family that returns operator-readable blocking and failure summaries assembled from workflow links, runs, approvals, tasks, checkpoints, and failure events.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite, pytest, pytest-asyncio

---

## File Structure

### Created Files

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\observability.py`
  New workflow observability query models, filter model, service, and derivation helpers.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_runs.py`
  New route family for tenant workflow run list and single-run observation detail.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_observability_service.py`
  New unit coverage for repository list behavior and observability-state derivation.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_runs_api.py`
  New integration coverage for the `/v1/workflow-runs` API family.

### Modified Files

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
  Add workflow-run list cursor helpers and tenant-scoped workflow-run list queries built on `workflow_run_links` + `runs`.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\repositories.py`
  Add read helpers for latest checkpoints, latest failure events, and pending approvals keyed by run.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
  Add dedicated API response schemas for workflow-run list items, pages, detail responses, and nested summaries.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
  Instantiate `WorkflowObservabilityService`, attach it to `app.state`, and include the new router.

- `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
  Add a concise workflow observability API usage section.

- `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`
  Document the new tenant workflow observability routes and field meanings for operators.

### Verification Commands

- Focused unit suite:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_observability_service.py -v`

- Focused integration suite:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_runs_api.py -v`

- Workflow-focused regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\unit\test_workflow_observability_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py tests\integration\test_workflow_runs_api.py -v`

- Full regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`

## Route Contract To Implement

- `GET /v1/workflow-runs`
  Required query: `tenant_id`
  Optional query: `workflow_id`, `template_version`, `status`, `created_after`, `created_before`, `cursor`, `limit`

- `GET /v1/workflow-runs/{run_id}`
  Required query: `tenant_id`
  Behavior: return `404` for nonexistent runs and for runs that are not workflow-linked in the given tenant

## Task 1: Add Red Unit Tests For Workflow Observability Query Semantics

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_observability_service.py`

- [ ] **Step 1: Write failing repository list tests for workflow-run filtering and pagination**

```python
import importlib
from datetime import UTC, datetime, timedelta

import pytest

from agent_runtime.domain.enums import AgentRole, RunStatus
from agent_runtime.domain.models import AgentRecord, RunRecord, WorkflowRunLinkRecord, WorkflowTemplateRecord, WorkflowTemplateVersionRecord
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.workflows.repository import WorkflowRepository


def load_workflow_observability_module():
    return importlib.import_module("agent_runtime.workflows.observability")


@pytest.mark.asyncio
async def test_workflow_repository_list_workflow_runs_filters_and_paginates(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = WorkflowRepository(session_factory)
        runtime_repository = RuntimeRepository(session_factory)

        base_time = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="triage",
                status="published",
                latest_version=2,
                latest_published_version=2,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=2,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                is_published=True,
            ),
        )

        for index, status in enumerate((RunStatus.FAILED, RunStatus.COMPLETED, RunStatus.RUNNING), start=1):
            run_id = f"run-{index}"
            created_at = base_time + timedelta(minutes=index)
            await runtime_repository.create_run(
                RunRecord(
                    run_id=run_id,
                    tenant_id="tenant-a",
                    objective=f"Triage INC-{index}",
                    status=status,
                    created_at=created_at,
                    updated_at=created_at,
                ),
                AgentRecord(
                    agent_id=f"agent-{index}",
                    run_id=run_id,
                    role=AgentRole.SUPERVISOR,
                    objective=f"Triage INC-{index}",
                    created_at=created_at,
                    updated_at=created_at,
                ),
            )
            await workflow_repository.create_run_link(
                WorkflowRunLinkRecord(
                    run_id=run_id,
                    tenant_id="tenant-a",
                    template_id="wf-triage",
                    template_version=2,
                    template_name="Incident Triage",
                    launch_input={"ticket_id": f"INC-{index}"},
                    launch_metadata={"requested_by": "ops"},
                    effective_workflow_policy={"allowed_tools": ["rag_search"]},
                    created_at=created_at,
                )
            )

        first_page = await workflow_repository.list_workflow_run_summaries(
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            template_version=2,
            status=RunStatus.RUNNING,
            created_after=None,
            created_before=None,
            limit=1,
            cursor=None,
        )

        assert [item["run_id"] for item in first_page["items"]] == ["run-3"]
        assert first_page["next_cursor"] is None
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 2: Write failing service tests for blocking-state and failure-summary derivation**

```python
@pytest.mark.asyncio
async def test_workflow_observability_service_derives_waiting_for_approval_and_failure_summary(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = WorkflowRepository(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        observability_module = load_workflow_observability_module()

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="triage",
                status="published",
                latest_version=1,
                latest_published_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                is_published=True,
            ),
        )

        service = observability_module.WorkflowObservabilityService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
        )

        waiting = observability_module._derive_observation_status(
            run_status="running",
            pending_approval_count=1,
            running_task_count=0,
        )
        worker_wait = observability_module._derive_observation_status(
            run_status="running",
            pending_approval_count=0,
            running_task_count=1,
        )
        failure_summary = observability_module._derive_failure_summary(
            run_error="tool timed out",
            latest_failure_event_error="ignored event error",
            latest_checkpoint_step="waiting_for_tool",
        )

        assert waiting == "waiting_for_approval"
        assert worker_wait == "waiting_on_worker"
        assert failure_summary == "tool timed out"
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 3: Write a failing detail test for tenant guardrails and non-workflow run exclusion**

```python
@pytest.mark.asyncio
async def test_workflow_observability_service_rejects_non_workflow_run_detail(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_repository = WorkflowRepository(session_factory)
        observability_module = load_workflow_observability_module()

        await runtime_repository.create_run(
            RunRecord(
                run_id="plain-run",
                tenant_id="tenant-a",
                objective="plain runtime run",
            ),
            AgentRecord(
                agent_id="plain-agent",
                run_id="plain-run",
                role=AgentRole.SUPERVISOR,
                objective="plain runtime run",
            ),
        )

        service = observability_module.WorkflowObservabilityService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
        )

        with pytest.raises(observability_module.WorkflowRunObservationNotFoundError, match="workflow run not found"):
            await service.get_workflow_run_detail(tenant_id="tenant-a", run_id="plain-run")
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 4: Run the focused unit suite to verify the new tests fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_observability_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_runtime.workflows.observability'` and missing `list_workflow_run_summaries(...)`.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_workflow_observability_service.py
git commit -m "test: add workflow observability red tests"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 2: Implement Workflow-Run Repository Queries And Runtime Read Helpers

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\repositories.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_observability_service.py`

- [ ] **Step 1: Add workflow-run cursor helpers and list-query method in `workflows/repository.py`**

```python
WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE = "invalid workflow run list cursor"
WORKFLOW_RUN_LIST_CURSOR_VERSION = 1


def encode_workflow_run_list_cursor(*, created_at: datetime, run_id: str) -> str:
    payload = {
        "v": WORKFLOW_RUN_LIST_CURSOR_VERSION,
        "created_at": _format_cursor_datetime(created_at),
        "run_id": run_id,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return encoded.decode("ascii")


def decode_workflow_run_list_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (UnicodeEncodeError, binascii.Error, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("v") != WORKFLOW_RUN_LIST_CURSOR_VERSION
        or not isinstance(payload.get("created_at"), str)
        or not isinstance(payload.get("run_id"), str)
        or not payload["run_id"]
    ):
        raise ValueError(WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE)

    return datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00")).astimezone(UTC), payload["run_id"]


async def list_workflow_run_summaries(
    self,
    *,
    tenant_id: str,
    workflow_id: str | None,
    template_version: int | None,
    status: RunStatus | None,
    created_after: datetime | None,
    created_before: datetime | None,
    limit: int,
    cursor: str | None,
) -> dict[str, object]:
    query = (
        select(
            WorkflowRunLinkTable.run_id,
            WorkflowRunLinkTable.tenant_id,
            WorkflowRunLinkTable.template_id,
            WorkflowRunLinkTable.template_name,
            WorkflowRunLinkTable.template_version,
            WorkflowRunLinkTable.created_at.label("started_at"),
            RunTable.status,
            RunTable.error,
            RunTable.updated_at.label("last_updated_at"),
        )
        .join(RunTable, RunTable.run_id == WorkflowRunLinkTable.run_id)
        .where(WorkflowRunLinkTable.tenant_id == tenant_id)
    )

    if workflow_id:
        query = query.where(WorkflowRunLinkTable.template_id == workflow_id)
    if template_version is not None:
        query = query.where(WorkflowRunLinkTable.template_version == template_version)
    if status is not None:
        query = query.where(RunTable.status == status.value)
    if created_after is not None:
        query = query.where(WorkflowRunLinkTable.created_at >= created_after)
    if created_before is not None:
        query = query.where(WorkflowRunLinkTable.created_at <= created_before)
    if cursor is not None:
        cursor_created_at, cursor_run_id = decode_workflow_run_list_cursor(cursor)
        query = query.where(
            or_(
                WorkflowRunLinkTable.created_at < cursor_created_at,
                and_(
                    WorkflowRunLinkTable.created_at == cursor_created_at,
                    WorkflowRunLinkTable.run_id > cursor_run_id,
                ),
            )
        )

    query = query.order_by(
        WorkflowRunLinkTable.created_at.desc(),
        WorkflowRunLinkTable.run_id.asc(),
    ).limit(limit + 1)

    async with self._session_factory() as session:
        rows = (await session.execute(query)).mappings().all()

    visible_rows = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last_visible = visible_rows[-1]
        next_cursor = encode_workflow_run_list_cursor(
            created_at=last_visible["started_at"],
            run_id=last_visible["run_id"],
        )

    return {"items": [dict(row) for row in visible_rows], "next_cursor": next_cursor}
```

- [ ] **Step 2: Add runtime batch read helpers for approvals, failure events, and latest checkpoints**

```python
async def list_pending_approvals_by_run_ids(self, run_ids: list[str]) -> dict[str, list[ApprovalRequestRecord]]:
    if not run_ids:
        return {}
    async with self._session_factory() as session:
        rows = (
            await session.execute(
                select(ApprovalRequestTable)
                .where(
                    ApprovalRequestTable.run_id.in_(run_ids),
                    ApprovalRequestTable.status == ApprovalStatus.PENDING.value,
                )
                .order_by(ApprovalRequestTable.created_at, ApprovalRequestTable.approval_id)
            )
        ).scalars().all()
    grouped = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped.setdefault(row.run_id, []).append(
            ApprovalRequestRecord(
                approval_id=row.approval_id,
                tenant_id=row.tenant_id,
                run_id=row.run_id,
                agent_id=row.agent_id,
                tool_name=row.tool_name,
                reason=row.reason,
                status=ApprovalStatus(row.status),
                resolution_note=row.resolution_note,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return grouped


async def get_latest_checkpoint_by_run_id(self, run_id: str) -> CheckpointRecord | None:
    async with self._session_factory() as session:
        row = (
            await session.execute(
                select(CheckpointTable)
                .where(CheckpointTable.run_id == run_id)
                .order_by(CheckpointTable.created_at.desc(), CheckpointTable.checkpoint_id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return CheckpointRecord(
        checkpoint_id=row.checkpoint_id,
        run_id=row.run_id,
        agent_id=row.agent_id,
        step_name=row.step_name,
        payload=row.payload,
        created_at=row.created_at,
    )


async def get_latest_failure_event_by_run_id(self, run_id: str) -> RuntimeEvent | None:
    async with self._session_factory() as session:
        row = (
            await session.execute(
                select(EventTable)
                .where(
                    EventTable.run_id == run_id,
                    EventTable.event_type == EventType.RUN_FAILED.value,
                )
                .order_by(EventTable.created_at.desc(), EventTable.event_id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return RuntimeEvent(
        event_id=row.event_id,
        tenant_id=row.tenant_id,
        run_id=row.run_id,
        agent_id=row.agent_id,
        event_type=EventType(row.event_type),
        payload=row.payload,
        created_at=row.created_at,
    )
```

- [ ] **Step 3: Run the unit suite again to confirm repository helpers exist but service tests still fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_observability_service.py -v`
Expected: FAIL only on missing `WorkflowObservabilityService`, missing derivation helpers, or missing detail assembly behavior.

- [ ] **Step 4: Commit**

```bash
git add src/agent_runtime/workflows/repository.py src/agent_runtime/state/repositories.py
git commit -m "feat: add workflow observability repository queries"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 3: Implement Workflow Observability Models And Service Assembly

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\observability.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_observability_service.py`

- [ ] **Step 1: Create filter and response query models**

```python
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_runtime.domain.enums import RunStatus


ObservationState = Literal[
    "running",
    "waiting_for_approval",
    "waiting_on_worker",
    "failed",
    "completed",
    "cancelled",
    "unknown",
]


class WorkflowRunObservationFilter(BaseModel):
    tenant_id: str
    workflow_id: str | None = None
    template_version: int | None = None
    status: RunStatus | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    cursor: str | None = None
    limit: int = 20


class WorkflowRunPendingApprovalSummary(BaseModel):
    approval_id: str
    tool_name: str
    reason: str
    created_at: datetime


class WorkflowRunObservationListItem(BaseModel):
    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_name: str
    template_version: int
    status: str
    current_blocking_state: ObservationState
    current_blocking_state_reason: str | None = None
    latest_failure_summary: str | None = None
    latest_checkpoint_step: str | None = None
    started_at: datetime
    last_updated_at: datetime
    pending_approval: WorkflowRunPendingApprovalSummary | None = None
```

- [ ] **Step 2: Implement derivation helpers and the service list/detail methods**

```python
class WorkflowRunObservationNotFoundError(RuntimeError):
    pass


def _derive_observation_status(*, run_status: str, pending_approval_count: int, running_task_count: int) -> ObservationState:
    if run_status == "completed":
        return "completed"
    if run_status == "failed":
        return "failed"
    if run_status == "cancelled":
        return "cancelled"
    if pending_approval_count > 0:
        return "waiting_for_approval"
    if running_task_count > 0:
        return "waiting_on_worker"
    if run_status in {"created", "running", "paused", "waiting_for_approval"}:
        return "running"
    return "unknown"


def _derive_failure_summary(*, run_error: str | None, latest_failure_event_error: str | None, latest_checkpoint_step: str | None) -> str | None:
    if run_error:
        return run_error
    if latest_failure_event_error:
        return latest_failure_event_error
    if latest_checkpoint_step:
        return f"latest checkpoint step: {latest_checkpoint_step}"
    return None


class WorkflowObservabilityService:
    def __init__(self, *, workflow_repository: WorkflowRepository, runtime_repository: RuntimeRepository) -> None:
        self._workflow_repository = workflow_repository
        self._runtime_repository = runtime_repository

    async def list_workflow_runs(self, filters: WorkflowRunObservationFilter) -> dict[str, object]:
        raw_page = await self._workflow_repository.list_workflow_run_summaries(
            tenant_id=filters.tenant_id,
            workflow_id=filters.workflow_id,
            template_version=filters.template_version,
            status=filters.status,
            created_after=filters.created_after,
            created_before=filters.created_before,
            limit=filters.limit,
            cursor=filters.cursor,
        )
        items = [
            await self._assemble_list_item(row["run_id"], row)
            for row in raw_page["items"]
        ]
        return {"items": items, "next_cursor": raw_page["next_cursor"]}

    async def _assemble_list_item(self, run_id: str, row: dict[str, object]) -> WorkflowRunObservationListItem:
        approvals_by_run = await self._runtime_repository.list_pending_approvals_by_run_ids([run_id])
        pending_approvals = approvals_by_run.get(run_id, [])
        latest_checkpoint = await self._runtime_repository.get_latest_checkpoint_by_run_id(run_id)
        latest_failure_event = await self._runtime_repository.get_latest_failure_event_by_run_id(run_id)
        current_blocking_state = _derive_observation_status(
            run_status=str(row["status"]),
            pending_approval_count=len(pending_approvals),
            running_task_count=0,
        )
        return WorkflowRunObservationListItem(
            run_id=str(row["run_id"]),
            tenant_id=str(row["tenant_id"]),
            workflow_id=str(row["template_id"]),
            workflow_name=str(row["template_name"]),
            template_version=int(row["template_version"]),
            status=str(row["status"]),
            current_blocking_state=current_blocking_state,
            current_blocking_state_reason=(
                f"waiting for approval on tool {pending_approvals[0].tool_name}"
                if pending_approvals
                else None
            ),
            latest_failure_summary=_derive_failure_summary(
                run_error=(str(row["error"]) if row["error"] is not None else None),
                latest_failure_event_error=(latest_failure_event.payload.get("error") if latest_failure_event else None),
                latest_checkpoint_step=(latest_checkpoint.step_name if latest_checkpoint else None),
            ),
            latest_checkpoint_step=(latest_checkpoint.step_name if latest_checkpoint else None),
            started_at=row["started_at"],
            last_updated_at=row["last_updated_at"],
            pending_approval=(
                WorkflowRunPendingApprovalSummary(
                    approval_id=pending_approvals[0].approval_id,
                    tool_name=pending_approvals[0].tool_name,
                    reason=pending_approvals[0].reason,
                    created_at=pending_approvals[0].created_at,
                )
                if pending_approvals
                else None
            ),
        )

    async def get_workflow_run_detail(self, *, tenant_id: str, run_id: str) -> dict[str, object]:
        run_link = await self._workflow_repository.get_run_link(run_id)
        if run_link is None or run_link.tenant_id != tenant_id:
            raise WorkflowRunObservationNotFoundError(f"workflow run not found: {run_id}")
        run = await self._runtime_repository.get_run(run_id)
        if run is None or run.tenant_id != tenant_id:
            raise WorkflowRunObservationNotFoundError(f"workflow run not found: {run_id}")
        agents = await self._runtime_repository.list_agents(run_id)
        tasks = await self._runtime_repository.list_tasks(run_id)
        approvals_by_run = await self._runtime_repository.list_pending_approvals_by_run_ids([run_id])
        latest_checkpoint = await self._runtime_repository.get_latest_checkpoint_by_run_id(run_id)
        latest_failure_event = await self._runtime_repository.get_latest_failure_event_by_run_id(run_id)
        pending_approvals = approvals_by_run.get(run_id, [])
        blocking_state = _derive_observation_status(
            run_status=run.status.value,
            pending_approval_count=len(pending_approvals),
            running_task_count=sum(1 for task in tasks if task.status.value == "running"),
        )
        return {
            "run": run.model_dump(mode="json"),
            "workflow": {
                "workflow_id": run_link.template_id,
                "workflow_name": run_link.template_name,
                "template_version": run_link.template_version,
                "launch_input": run_link.launch_input,
                "launch_metadata": run_link.launch_metadata,
            },
            "agents": [agent.model_dump(mode="json") for agent in agents],
            "tasks": [task.model_dump(mode="json") for task in tasks],
            "latest_checkpoint": (latest_checkpoint.model_dump(mode="json") if latest_checkpoint else None),
            "pending_approval": (
                pending_approvals[0].model_dump(mode="json")
                if pending_approvals
                else None
            ),
            "current_blocking_state": blocking_state,
            "latest_failure_summary": _derive_failure_summary(
                run_error=run.error,
                latest_failure_event_error=(latest_failure_event.payload.get("error") if latest_failure_event else None),
                latest_checkpoint_step=(latest_checkpoint.step_name if latest_checkpoint else None),
            ),
        }
```

- [ ] **Step 3: Run the focused unit suite and make it pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_observability_service.py -v`
Expected: PASS for repository list, derivation helpers, and non-workflow detail rejection.

- [ ] **Step 4: Commit**

```bash
git add src/agent_runtime/workflows/observability.py tests/unit/test_workflow_observability_service.py
git commit -m "feat: add workflow observability service"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 4: Add API Schemas, Routes, App Wiring, And Integration Coverage

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_runs.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_runs_api.py`

- [ ] **Step 1: Write failing integration tests for list filters, detail, and non-workflow exclusion**

```python
import pytest

from agent_runtime.api.app import create_app
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


@pytest.mark.asyncio
async def test_workflow_runs_api_lists_tenant_workflow_runs_with_filters(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        response = await client.get(
            "/v1/workflow-runs",
            params={
                "tenant_id": "tenant-a",
                "workflow_id": "wf-triage",
                "status": "running",
                "limit": "10",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"items", "next_cursor"}


@pytest.mark.asyncio
async def test_workflow_runs_api_detail_rejects_plain_run(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        create_run_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "plain runtime run"},
        )
        run_id = create_run_response.json()["run_id"]

        detail_response = await client.get(
            f"/v1/workflow-runs/{run_id}",
            params={"tenant_id": "tenant-a"},
        )

    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == f"workflow run not found: {run_id}"
```

- [ ] **Step 2: Run the focused integration suite to confirm the routes are missing**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_runs_api.py -v`
Expected: FAIL with `404` for `/v1/workflow-runs` because the router has not been wired yet.

- [ ] **Step 3: Implement API schemas and the new `/v1/workflow-runs` router**

```python
class WorkflowRunObservationListItemResponse(BaseModel):
    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_name: str
    template_version: int
    status: str
    current_blocking_state: str
    current_blocking_state_reason: str | None = None
    latest_failure_summary: str | None = None
    latest_checkpoint_step: str | None = None
    started_at: datetime
    last_updated_at: datetime
    pending_approval: dict[str, Any] | None = None


class WorkflowRunObservationListResponse(BaseModel):
    items: list[WorkflowRunObservationListItemResponse] = Field(default_factory=list)
    next_cursor: str | None = None


class WorkflowRunObservationDetailResponse(BaseModel):
    run: dict[str, Any]
    workflow: dict[str, Any]
    agents: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    latest_checkpoint: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
    current_blocking_state: str
    latest_failure_summary: str | None = None


def _parse_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an ISO-8601 datetime") from exc


def _parse_limit(value: str | None) -> int:
    if value is None:
        return 20
    try:
        parsed = int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100") from exc
    if parsed < 1 or parsed > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return parsed


def _parse_template_version(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="template_version must be an integer") from exc


def _parse_status(value: str | None) -> RunStatus | None:
    if value is None:
        return None
    try:
        return RunStatus(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="status must be a valid run status") from exc


router = APIRouter(prefix="/v1/workflow-runs", tags=["workflow-runs"])


@router.get("", response_model=WorkflowRunObservationListResponse)
async def list_workflow_runs(
    request: Request,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    template_version: str | None = None,
    status: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    cursor: str | None = None,
    limit: str | None = None,
) -> WorkflowRunObservationListResponse:
    if tenant_id is None or not tenant_id.strip():
        raise HTTPException(status_code=400, detail="tenant_id is required")
    filters = WorkflowRunObservationFilter(
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        template_version=_parse_template_version(template_version),
        status=_parse_status(status),
        created_after=_parse_datetime(created_after, "created_after"),
        created_before=_parse_datetime(created_before, "created_before"),
        cursor=cursor,
        limit=_parse_limit(limit),
    )
    page = await request.app.state.workflow_observability_service.list_workflow_runs(filters)
    return WorkflowRunObservationListResponse(
        items=[WorkflowRunObservationListItemResponse.model_validate(item.model_dump()) for item in page["items"]],
        next_cursor=page["next_cursor"],
    )


@router.get("/{run_id}", response_model=WorkflowRunObservationDetailResponse)
async def get_workflow_run_detail(request: Request, run_id: str, tenant_id: str) -> WorkflowRunObservationDetailResponse:
    try:
        detail = await request.app.state.workflow_observability_service.get_workflow_run_detail(
            tenant_id=tenant_id,
            run_id=run_id,
        )
    except WorkflowRunObservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkflowRunObservationDetailResponse.model_validate(detail)
```

- [ ] **Step 4: Wire the new service and router into `create_app()`**

```python
from agent_runtime.api.routes.workflow_runs import router as workflow_runs_router
from agent_runtime.workflows.observability import WorkflowObservabilityService


workflow_observability_service = WorkflowObservabilityService(
    workflow_repository=workflow_repository,
    runtime_repository=repository,
)

app.state.workflow_observability_service = workflow_observability_service
app.include_router(workflow_runs_router)
```

- [ ] **Step 5: Run the focused integration suite and make it pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_runs_api.py -v`
Expected: PASS for list, detail, and non-workflow exclusion behavior.

- [ ] **Step 6: Commit**

```bash
git add src/agent_runtime/api/schemas.py src/agent_runtime/api/routes/workflow_runs.py src/agent_runtime/api/app.py tests/integration/test_workflow_runs_api.py
git commit -m "feat: add workflow run observability api"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 5: Document The New API And Run Regression Verification

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`

- [ ] **Step 1: Add a concise README section for the new workflow observability endpoints**

```md
## Workflow Run Observability

The runtime now exposes tenant-scoped workflow observability APIs:

- `GET /v1/workflow-runs?tenant_id=<tenant>`
- `GET /v1/workflow-runs/{run_id}?tenant_id=<tenant>`

The list endpoint returns workflow-linked run summaries with:

- workflow identifier and launched version
- top-level run status
- derived `current_blocking_state`
- derived `current_blocking_state_reason`
- `latest_failure_summary`
- `latest_checkpoint_step`

Use the detail endpoint when an operator needs the current checkpoint, pending approval context, agent/task summaries, and the event replay handoff for a single workflow run.
```

- [ ] **Step 2: Add runbook notes explaining field semantics and intended operator workflow**

```md
### Workflow Run Observability

Use `GET /v1/workflow-runs` to triage workflow-started runs for a single tenant.

Field intent:

- `current_blocking_state`: operator-facing derived state, not a raw runtime enum
- `current_blocking_state_reason`: short explanation of the current wait or block condition
- `latest_failure_summary`: best available failure explanation from `run.error`, failure event payloads, or checkpoint context
- `latest_checkpoint_step`: most recent checkpoint step name for fast execution-position inspection

Use `GET /v1/workflow-runs/{run_id}` when deeper context is needed before falling back to `GET /v1/runs/{run_id}/events/replay`.
```

- [ ] **Step 3: Run the workflow-focused regression suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\unit\test_workflow_observability_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py tests\integration\test_workflow_runs_api.py -v`
Expected: PASS with the new workflow observability tests included.

- [ ] **Step 4: Run the full regression suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS, with any pre-existing documented `aiosqlite` warning behavior unchanged from the current baseline.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations-runbook.md
git commit -m "docs: document workflow observability api"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Self-Review Checklist

- Spec coverage:
  - tenant-scoped workflow-run list query is covered by Tasks 1, 2, and 4
  - workflow-run detail assembly is covered by Tasks 3 and 4
  - blocking/failure derivation is covered by Tasks 1 and 3
  - docs and verification are covered by Task 5

- Placeholder scan:
  - no `TBD`, `TODO`, or implicit “similar to above” references remain
  - all code-edit steps contain concrete snippets
  - all verification steps contain exact commands

- Type consistency:
  - route family is consistently `/v1/workflow-runs`
  - service name is consistently `WorkflowObservabilityService`
  - detail error type is consistently `WorkflowRunObservationNotFoundError`
  - response terminology consistently uses `workflow_id`, `template_version`, `current_blocking_state`, and `latest_failure_summary`
