from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_runtime.domain.enums import AgentRole, RunStatus, TaskStatus
from agent_runtime.domain.models import ApprovalRequestRecord, RuntimeEvent
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.workflows.repository import WorkflowRepository

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
    limit: int = Field(default=20, ge=1)
    cursor: str | None = None


class WorkflowRunPendingApprovalSummary(BaseModel):
    approval_id: str
    agent_id: str
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


class WorkflowRunObservationNotFoundError(RuntimeError):
    pass


def _derive_observation_status(
    *,
    run_status: str,
    pending_approval_count: int,
    running_task_count: int,
) -> ObservationState:
    if run_status == RunStatus.COMPLETED.value:
        return "completed"
    if run_status == RunStatus.FAILED.value:
        return "failed"
    if run_status == RunStatus.CANCELLED.value:
        return "cancelled"
    if pending_approval_count > 0:
        return "waiting_for_approval"
    if running_task_count > 0:
        return "waiting_on_worker"
    if run_status in {
        RunStatus.CREATED.value,
        RunStatus.RUNNING.value,
        RunStatus.PAUSED.value,
        RunStatus.WAITING_FOR_APPROVAL.value,
    }:
        return "running"
    return "unknown"


def _derive_failure_summary(
    *,
    run_error: str | None,
    latest_failure_event_error: str | None,
    latest_checkpoint_step: str | None,
) -> str | None:
    if run_error:
        return run_error
    if latest_failure_event_error:
        return latest_failure_event_error
    if latest_checkpoint_step:
        return latest_checkpoint_step
    return None


class WorkflowObservabilityService:
    _derive_observation_status = staticmethod(_derive_observation_status)
    _derive_failure_summary = staticmethod(_derive_failure_summary)

    def __init__(
        self,
        *,
        workflow_repository: WorkflowRepository,
        runtime_repository: RuntimeRepository,
    ) -> None:
        self._workflow_repository = workflow_repository
        self._runtime_repository = runtime_repository

    async def list_workflow_runs(self, filters: WorkflowRunObservationFilter) -> dict[str, object]:
        summaries = await self._workflow_repository.list_workflow_run_summaries(
            tenant_id=filters.tenant_id,
            workflow_id=filters.workflow_id,
            template_version=filters.template_version,
            status=filters.status,
            created_after=filters.created_after,
            created_before=filters.created_before,
            limit=filters.limit,
            cursor=filters.cursor,
        )
        rows: list[dict[str, object]] = []
        run_ids: list[str] = []
        for row in summaries["items"]:
            if not isinstance(row, dict):
                raise RuntimeError(f"expected workflow run summary row dict, got {type(row).__name__}")
            run_id = str(row["run_id"])
            rows.append(row)
            run_ids.append(run_id)

        approvals_by_run_id = await self._runtime_repository.list_pending_approvals_by_run_ids(run_ids)
        items = list(
            await asyncio.gather(
                *[
                    self._assemble_list_item(
                        run_id,
                        row,
                        approvals_by_run_id=approvals_by_run_id,
                    )
                    for run_id, row in zip(run_ids, rows, strict=False)
                ]
            )
        )
        return {
            "items": items,
            "next_cursor": summaries["next_cursor"],
        }

    async def _assemble_list_item(
        self,
        run_id: str,
        row: dict[str, object],
        *,
        approvals_by_run_id: dict[str, list[ApprovalRequestRecord]] | None = None,
    ) -> WorkflowRunObservationListItem:
        pending_approval = (
            self._get_pending_approval_summary_from_lookup(run_id, approvals_by_run_id)
            if approvals_by_run_id is not None
            else await self._get_pending_approval_summary(run_id)
        )
        tasks, latest_checkpoint, latest_failure_event = await asyncio.gather(
            self._runtime_repository.list_tasks(run_id),
            self._runtime_repository.get_latest_checkpoint_by_run_id(
                run_id,
                agent_role=AgentRole.SUPERVISOR,
            ),
            self._runtime_repository.get_latest_failure_event_by_run_id(run_id),
        )
        run_status = self._as_str(row.get("status"))
        run_error = self._as_optional_str(row.get("error"))
        running_task_count = sum(1 for task in tasks if task.status == TaskStatus.RUNNING)
        latest_checkpoint_step = latest_checkpoint.step_name if latest_checkpoint is not None else None
        latest_failure_event_error = self._extract_failure_event_error(latest_failure_event)
        latest_failure_summary = self._derive_failure_summary(
            run_error=run_error,
            latest_failure_event_error=latest_failure_event_error,
            latest_checkpoint_step=(
                latest_checkpoint_step
                if self._has_failure_context(
                    run_status=run_status,
                    run_error=run_error,
                    latest_failure_event_error=latest_failure_event_error,
                )
                else None
            ),
        )
        current_blocking_state = self._derive_observation_status(
            run_status=run_status,
            pending_approval_count=1 if pending_approval is not None else 0,
            running_task_count=running_task_count,
        )

        return WorkflowRunObservationListItem(
            run_id=run_id,
            tenant_id=self._as_str(row.get("tenant_id")),
            workflow_id=self._as_str(row.get("template_id")),
            workflow_name=self._as_str(row.get("template_name")),
            template_version=int(row["template_version"]),
            status=run_status,
            current_blocking_state=current_blocking_state,
            current_blocking_state_reason=self._derive_blocking_state_reason(
                current_blocking_state=current_blocking_state,
                pending_approval=pending_approval,
                running_task_count=running_task_count,
                latest_failure_summary=latest_failure_summary,
            ),
            latest_failure_summary=latest_failure_summary,
            latest_checkpoint_step=latest_checkpoint_step,
            started_at=self._as_datetime(row.get("started_at")),
            last_updated_at=self._as_datetime(row.get("last_updated_at")),
            pending_approval=pending_approval,
        )

    async def get_workflow_run_detail(self, *, tenant_id: str, run_id: str) -> dict[str, object]:
        run_link = await self._workflow_repository.get_run_link(run_id)
        if run_link is None or run_link.tenant_id != tenant_id:
            raise WorkflowRunObservationNotFoundError(f"workflow run not found: {run_id}")

        run = await self._runtime_repository.get_run(run_id)
        if run is None or run.tenant_id != tenant_id:
            raise WorkflowRunObservationNotFoundError(f"workflow run not found: {run_id}")

        agents, tasks, pending_approval, latest_checkpoint, latest_failure_event = await asyncio.gather(
            self._runtime_repository.list_agents(run_id),
            self._runtime_repository.list_tasks(run_id),
            self._get_pending_approval_summary(run_id),
            self._runtime_repository.get_latest_checkpoint_by_run_id(
                run_id,
                agent_role=AgentRole.SUPERVISOR,
            ),
            self._runtime_repository.get_latest_failure_event_by_run_id(run_id),
        )
        latest_checkpoint_step = latest_checkpoint.step_name if latest_checkpoint is not None else None
        latest_failure_event_error = self._extract_failure_event_error(latest_failure_event)
        latest_failure_summary = self._derive_failure_summary(
            run_error=run.error,
            latest_failure_event_error=latest_failure_event_error,
            latest_checkpoint_step=(
                latest_checkpoint_step
                if self._has_failure_context(
                    run_status=run.status.value,
                    run_error=run.error,
                    latest_failure_event_error=latest_failure_event_error,
                )
                else None
            ),
        )
        current_blocking_state = self._derive_observation_status(
            run_status=run.status.value,
            pending_approval_count=1 if pending_approval is not None else 0,
            running_task_count=sum(1 for task in tasks if task.status == TaskStatus.RUNNING),
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
            "latest_checkpoint": None if latest_checkpoint is None else latest_checkpoint.model_dump(mode="json"),
            "pending_approval": None if pending_approval is None else pending_approval.model_dump(mode="json"),
            "current_blocking_state": current_blocking_state,
            "latest_failure_summary": latest_failure_summary,
        }

    async def _get_pending_approval_summary(
        self,
        run_id: str,
    ) -> WorkflowRunPendingApprovalSummary | None:
        approvals_by_run_id = await self._runtime_repository.list_pending_approvals_by_run_ids([run_id])
        pending_approvals = approvals_by_run_id.get(run_id, [])
        if not pending_approvals:
            return None

        approval = pending_approvals[0]
        return self._to_pending_approval_summary(approval)

    def _get_pending_approval_summary_from_lookup(
        self,
        run_id: str,
        approvals_by_run_id: dict[str, list[ApprovalRequestRecord]] | None,
    ) -> WorkflowRunPendingApprovalSummary | None:
        if approvals_by_run_id is None:
            return None

        pending_approvals = approvals_by_run_id.get(run_id, [])
        if not pending_approvals:
            return None

        return self._to_pending_approval_summary(pending_approvals[0])

    @staticmethod
    def _to_pending_approval_summary(
        approval: ApprovalRequestRecord,
    ) -> WorkflowRunPendingApprovalSummary:
        return WorkflowRunPendingApprovalSummary(
            approval_id=approval.approval_id,
            agent_id=approval.agent_id,
            tool_name=approval.tool_name,
            reason=approval.reason,
            created_at=approval.created_at,
        )

    @staticmethod
    def _extract_failure_event_error(event: RuntimeEvent | None) -> str | None:
        if event is None:
            return None
        error = event.payload.get("error")
        return error if isinstance(error, str) and error else None

    @staticmethod
    def _has_failure_context(
        *,
        run_status: str,
        run_error: str | None,
        latest_failure_event_error: str | None,
    ) -> bool:
        return bool(
            run_error
            or latest_failure_event_error
            or run_status == RunStatus.FAILED.value
        )

    @staticmethod
    def _derive_blocking_state_reason(
        *,
        current_blocking_state: ObservationState,
        pending_approval: WorkflowRunPendingApprovalSummary | None,
        running_task_count: int,
        latest_failure_summary: str | None,
    ) -> str | None:
        if current_blocking_state == "waiting_for_approval" and pending_approval is not None:
            return pending_approval.reason
        if current_blocking_state == "waiting_on_worker" and running_task_count > 0:
            return f"{running_task_count} running task(s)"
        if current_blocking_state == "failed":
            return latest_failure_summary
        return None

    @staticmethod
    def _as_str(value: object) -> str:
        if isinstance(value, str):
            return value
        raise RuntimeError(f"expected string value, got {type(value).__name__}")

    @staticmethod
    def _as_optional_str(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        raise RuntimeError(f"expected optional string value, got {type(value).__name__}")

    @staticmethod
    def _as_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            return value
        raise RuntimeError(f"expected datetime value, got {type(value).__name__}")
