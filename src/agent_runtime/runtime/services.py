from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from agent_runtime.domain.enums import AgentRole, AgentStatus, ApprovalStatus, EventType, RunStatus
from agent_runtime.domain.models import (
    AgentRecord,
    ApprovalRequestRecord,
    RunRecord,
    RuntimeEvent,
    WorkflowRunLinkRecord,
)
from agent_runtime.models.base import ModelClient
from agent_runtime.observability.context import get_request_context
from agent_runtime.observability.logging import emit_structured_log
from agent_runtime.observability.metrics import MetricsSink
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.runtime.resume import ResumeCoordinator
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.testing.faults import FaultInjector, FaultPoint, NoopFaultInjector
from agent_runtime.tools.gateway import ToolGateway
from agent_runtime.workflows.repository import WorkflowRepository


class RunService:
    _STARTUP_RESUMABLE_AGENT_STATUSES = {
        AgentStatus.CREATED,
        AgentStatus.READY,
        AgentStatus.REASONING,
        AgentStatus.WAITING_ON_WORKERS,
    }

    def __init__(
        self,
        repository: RuntimeRepository,
        model_client: ModelClient,
        event_hub: EventStreamHub,
        *,
        tool_gateway: ToolGateway | None = None,
        workflow_repository: WorkflowRepository | None = None,
        metrics_sink: MetricsSink | None = None,
        runtime_logger: logging.Logger | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._repository = repository
        self._model_client = model_client
        self._event_hub = event_hub
        self._tool_gateway = tool_gateway
        self._workflow_repository = workflow_repository
        self._metrics_sink = metrics_sink
        self._runtime_logger = runtime_logger or logging.getLogger("agent_runtime.runtime")
        self._fault_injector = fault_injector or NoopFaultInjector()
        self._orchestrator = RuntimeOrchestrator(
            repository,
            model_client,
            event_hub,
            tool_gateway=tool_gateway,
            metrics_sink=metrics_sink,
            runtime_logger=self._runtime_logger,
            fault_injector=self._fault_injector,
        )
        self._resume = ResumeCoordinator(repository, self._orchestrator)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def create_run(
        self,
        tenant_id: str,
        objective: str,
        initial_observations: list[str] | None = None,
    ) -> RunRecord:
        run, supervisor = await self._persist_run(
            tenant_id,
            objective,
            initial_observations=initial_observations,
        )
        self._dispatch_run(
            run_id=run.run_id,
            tenant_id=tenant_id,
            agent_id=supervisor.agent_id,
        )
        return run

    async def _persist_run(
        self,
        tenant_id: str,
        objective: str,
        *,
        initial_observations: list[str] | None = None,
    ) -> tuple[RunRecord, AgentRecord]:
        run = RunRecord(tenant_id=tenant_id, objective=objective)
        supervisor = AgentRecord(
            run_id=run.run_id,
            role=AgentRole.SUPERVISOR,
            objective=objective,
            observations=list(initial_observations or []),
        )
        await self._repository.create_run(run, supervisor)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_CREATED,
                payload={"objective": objective},
            )
        )
        if self._metrics_sink is not None:
            self._metrics_sink.record_run_created()
        emit_structured_log(
            self._runtime_logger,
            "run created",
            component="run_service",
            context={
                **get_request_context(),
                "tenant_id": tenant_id,
                "run_id": run.run_id,
                "agent_id": supervisor.agent_id,
            },
            fields={"status": run.status.value},
        )
        return run, supervisor

    def _dispatch_run(self, *, run_id: str, tenant_id: str, agent_id: str) -> None:
        self._fault_injector.trigger(
            FaultPoint.RUN_CREATE_BEFORE_DISPATCH,
            tenant_id=tenant_id,
            run_id=run_id,
            agent_id=agent_id,
        )
        self._schedule_run_task(run_id)

    def _schedule_run_task(self, run_id: str) -> asyncio.Task[None]:
        task = asyncio.create_task(self._execute_run(run_id))
        self._tasks[run_id] = task
        return task

    async def create_run_from_template_launch(
        self,
        *,
        tenant_id: str,
        objective: str,
        template_id: str,
        template_version: int,
        template_name: str,
        launch_input: dict[str, object],
        launch_metadata: dict[str, object],
        effective_workflow_policy: dict[str, object],
    ) -> RunRecord:
        if self._workflow_repository is None:
            raise RuntimeError("workflow repository is not configured")

        run, supervisor = await self._persist_run(
            tenant_id,
            objective,
            initial_observations=self._workflow_default_kb_observations(effective_workflow_policy),
        )
        try:
            await self._workflow_repository.create_run_link(
                WorkflowRunLinkRecord(
                    run_id=run.run_id,
                    tenant_id=tenant_id,
                    template_id=template_id,
                    template_version=template_version,
                    template_name=template_name,
                    launch_input=launch_input,
                    launch_metadata=launch_metadata,
                    effective_workflow_policy=effective_workflow_policy,
                )
            )
        except Exception as exc:
            await self._repository.update_run_status(run.run_id, RunStatus.FAILED)
            event = RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_FAILED,
                payload={"error": str(exc), "reason": "workflow link persistence failed"},
            )
            await self._repository.append_event(event)
            await self._event_hub.publish(event)
            raise
        self._dispatch_run(
            run_id=run.run_id,
            tenant_id=tenant_id,
            agent_id=supervisor.agent_id,
        )
        return run

    @staticmethod
    def _workflow_default_kb_observations(
        effective_workflow_policy: dict[str, object],
    ) -> list[str] | None:
        raw_kb_ids = effective_workflow_policy.get("default_kb_ids")
        if not isinstance(raw_kb_ids, list):
            return None

        kb_ids = [kb_id.strip() for kb_id in raw_kb_ids if isinstance(kb_id, str) and kb_id.strip()]
        if not kb_ids:
            return None

        selected_ids = ", ".join(kb_ids)
        return [
            f"Selected knowledge bases for retrieval: {selected_ids}. Use these kb_ids when calling rag_search.",
        ]

    async def get_run(self, run_id: str) -> RunRecord:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        return run

    async def get_approval(self, approval_id: str) -> ApprovalRequestRecord:
        approval = await self._repository.get_approval_request(approval_id)
        if approval is None:
            raise RuntimeError(f"approval request not found: {approval_id}")
        return approval

    async def approve_approval(self, approval_id: str, *, resolution_note: str | None = None) -> None:
        approval = await self.get_approval(approval_id)
        self._ensure_pending_approval(approval)

        await self._repository.update_approval_request(
            approval_id,
            status=ApprovalStatus.APPROVED,
            resolution_note=resolution_note,
        )
        if self._metrics_sink is not None:
            self._metrics_sink.record_approval_resolution(status=ApprovalStatus.APPROVED.value)
        await self._emit_approval_resolved(
            approval=approval,
            status=ApprovalStatus.APPROVED,
            resolution_note=resolution_note,
        )
        await self._repository.update_run_status(approval.run_id, RunStatus.RUNNING)
        await self._repository.update_agent_state(
            approval.agent_id,
            status=AgentStatus.WAITING_ON_TOOL,
        )
        await self.resume_run(approval.run_id)

    async def reject_approval(self, approval_id: str, *, resolution_note: str | None = None) -> None:
        approval = await self.get_approval(approval_id)
        self._ensure_pending_approval(approval)

        await self._repository.update_approval_request(
            approval_id,
            status=ApprovalStatus.REJECTED,
            resolution_note=resolution_note,
        )
        if self._metrics_sink is not None:
            self._metrics_sink.record_approval_resolution(status=ApprovalStatus.REJECTED.value)
        await self._emit_approval_resolved(
            approval=approval,
            status=ApprovalStatus.REJECTED,
            resolution_note=resolution_note,
        )
        await self._orchestrator.fail_run(
            approval.run_id,
            f"approval rejected for tool: {approval.tool_name}",
        )

    async def resume_run(self, run_id: str) -> RunRecord:
        if run_id in self._tasks and not self._tasks[run_id].done():
            await self._tasks[run_id]
            return await self.get_run(run_id)

        try:
            self._fault_injector.trigger(FaultPoint.RUN_RESUME_BEFORE_EXECUTE, run_id=run_id)
        except Exception as exc:
            await self._orchestrator.fail_run(run_id, str(exc))
            if self._metrics_sink is not None:
                self._metrics_sink.record_run_failed()
            return await self.get_run(run_id)
        self._schedule_run_task(run_id)
        try:
            await self._tasks[run_id]
            return await self.get_run(run_id)
        finally:
            if self._tasks.get(run_id) is not None and self._tasks[run_id].done():
                self._tasks.pop(run_id, None)

    async def resume_active_runs(self) -> None:
        tasks = await self.resume_active_runs_in_background()
        if tasks:
            await asyncio.gather(*tasks)

    async def resume_active_runs_in_background(self) -> list[asyncio.Task[None]]:
        active_runs = await self._repository.list_active_runs()
        tasks: list[asyncio.Task[None]] = []
        for run in active_runs:
            if run.run_id in self._tasks and not self._tasks[run.run_id].done():
                continue
            startup_resume_error = await self._get_startup_resume_error(run.run_id)
            if startup_resume_error is not None:
                await self._orchestrator.fail_run(run.run_id, startup_resume_error)
                if self._metrics_sink is not None:
                    self._metrics_sink.record_run_failed()
                continue
            try:
                self._fault_injector.trigger(FaultPoint.RUN_RESUME_BEFORE_EXECUTE, run_id=run.run_id)
            except Exception as exc:
                await self._orchestrator.fail_run(run.run_id, str(exc))
                if self._metrics_sink is not None:
                    self._metrics_sink.record_run_failed()
                continue
            tasks.append(self._schedule_run_task(run.run_id))
        return tasks

    async def _get_startup_resume_error(self, run_id: str) -> str | None:
        agents = await self._repository.list_agents(run_id)
        if not agents:
            return None

        supervisor = agents[0]
        if supervisor.status in self._STARTUP_RESUMABLE_AGENT_STATUSES:
            return None

        return (
            "startup recovery skipped for unsafe agent state: "
            f"{supervisor.status.value}"
        )

    async def cancel_run(self, run_id: str) -> None:
        run = await self.get_run(run_id)
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        await self._repository.update_run_status(run_id, RunStatus.CANCELLED)
        event = RuntimeEvent.build(
            tenant_id=run.tenant_id,
            run_id=run_id,
            event_type=EventType.RUN_CANCELLED,
            payload={"reason": "cancelled by api"},
        )
        await self._repository.append_event(event)
        await self._event_hub.publish(event)

        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()

    async def replay_events(self, run_id: str) -> list[RuntimeEvent]:
        await self.get_run(run_id)
        return await self._repository.list_events(run_id)

    async def stream_events(self, run_id: str) -> AsyncIterator[str]:
        await self.get_run(run_id)

        async def event_stream() -> AsyncIterator[str]:
            async for event in self._event_hub.stream(run_id):
                yield f"data: {event.model_dump_json()}\n\n"

        return event_stream()

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_run(self, run_id: str) -> None:
        try:
            await self._orchestrator.execute_run(run_id)
            run = await self._repository.get_run(run_id)
            if run is not None and run.status == RunStatus.COMPLETED and self._metrics_sink is not None:
                self._metrics_sink.record_run_completed()
        except asyncio.CancelledError:
            run = await self._repository.get_run(run_id)
            if run is None or run.status == RunStatus.CANCELLED:
                return
            await self._orchestrator.fail_run(run_id, "run task cancelled unexpectedly")
            if self._metrics_sink is not None:
                self._metrics_sink.record_run_failed()
        except Exception as exc:
            await self._orchestrator.fail_run(run_id, str(exc))
            if self._metrics_sink is not None:
                self._metrics_sink.record_run_failed()
        finally:
            current_task = asyncio.current_task()
            if self._tasks.get(run_id) is current_task:
                self._tasks.pop(run_id, None)

    def _ensure_pending_approval(self, approval: ApprovalRequestRecord) -> None:
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"approval request already resolved: {approval.approval_id}")

    async def _emit_approval_resolved(
        self,
        *,
        approval: ApprovalRequestRecord,
        status: ApprovalStatus,
        resolution_note: str | None,
    ) -> None:
        event = RuntimeEvent.build(
            tenant_id=approval.tenant_id,
            run_id=approval.run_id,
            agent_id=approval.agent_id,
            event_type=EventType.APPROVAL_RESOLVED,
            payload={
                "approval_id": approval.approval_id,
                "tool_name": approval.tool_name,
                "status": status.value,
                "resolution_note": resolution_note,
            },
        )
        await self._repository.append_event(event)
        await self._event_hub.publish(event)
