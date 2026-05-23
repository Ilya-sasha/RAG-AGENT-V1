from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from agent_runtime.agents.profiles import ensure_predefined_worker
from agent_runtime.domain.enums import (
    AgentRole,
    AgentStatus,
    ApprovalStatus,
    DecisionKind,
    EventType,
    RunStatus,
    TaskStatus,
)
from agent_runtime.domain.models import (
    AgentRecord,
    CheckpointRecord,
    RunRecord,
    RuntimeEvent,
    TaskRecord,
)
from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput
from agent_runtime.observability.context import get_request_context
from agent_runtime.observability.logging import emit_structured_log
from agent_runtime.observability.metrics import MetricsSink
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.testing.faults import FaultInjector, FaultPoint, NoopFaultInjector
from agent_runtime.tools.base import ToolExecutionRequest
from agent_runtime.tools.gateway import ToolGateway


@dataclass(slots=True)
class RunCancelledError(Exception):
    run_id: str


class RuntimeOrchestrator:
    def __init__(
        self,
        repository: RuntimeRepository,
        model_client: ModelClient,
        event_hub: EventStreamHub,
        *,
        tool_gateway: ToolGateway | None = None,
        metrics_sink: MetricsSink | None = None,
        runtime_logger: logging.Logger | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._repository = repository
        self._model_client = model_client
        self._event_hub = event_hub
        self._tool_gateway = tool_gateway
        self._metrics_sink = metrics_sink
        self._runtime_logger = runtime_logger or logging.getLogger("agent_runtime.orchestrator")
        self._fault_injector = fault_injector or NoopFaultInjector()

    async def execute_run(self, run_id: str) -> None:
        try:
            run = await self._require_active_run(run_id)
            supervisor = await self._get_supervisor(run_id)
            latest_checkpoint = await self._repository.get_latest_checkpoint(
                run_id,
                supervisor.agent_id,
            )
            restored_observations = self._restore_observations(
                supervisor,
                latest_checkpoint,
            )
            await self._repository.update_run_status(run_id, RunStatus.RUNNING)
            await self._emit(
                RuntimeEvent.build(
                    tenant_id=run.tenant_id,
                    run_id=run.run_id,
                    agent_id=supervisor.agent_id,
                    event_type=EventType.RUN_STARTED,
                    payload={
                        "objective": run.objective,
                        "resumed": latest_checkpoint is not None,
                    },
                )
            )
            await self._repository.update_agent_state(
                supervisor.agent_id,
                observations=restored_observations,
            )
            await self._run_agent(run.tenant_id, supervisor.agent_id)
        except RunCancelledError:
            return

    async def _run_agent(self, tenant_id: str, agent_id: str) -> str:
        agent = await self._require_agent(agent_id)
        latest_checkpoint = await self._repository.get_latest_checkpoint(agent.run_id, agent.agent_id)
        restored_observations = self._restore_observations(
            agent,
            latest_checkpoint,
        )

        resumed_dispatch = await self._resume_existing_dispatch_if_present(
            tenant_id=tenant_id,
            agent=agent,
            latest_checkpoint=latest_checkpoint,
            restored_observations=restored_observations,
        )
        if resumed_dispatch is not None:
            return resumed_dispatch

        resumed_tool = await self._resume_waiting_tool_if_present(
            tenant_id=tenant_id,
            agent=agent,
            latest_checkpoint=latest_checkpoint,
            restored_observations=restored_observations,
        )
        if resumed_tool is not None:
            return resumed_tool

        await self._ensure_active(agent.run_id)
        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.REASONING,
            observations=restored_observations,
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.AGENT_STARTED,
                payload={"role": agent.role.value},
            )
        )
        checkpoint = CheckpointRecord(
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            step_name="before_model",
            payload={"observations": restored_observations},
        )
        await self._repository.save_checkpoint(checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": checkpoint.step_name},
            )
        )

        self._fault_injector.trigger(
            FaultPoint.MODEL_BEFORE_COMPLETE,
            tenant_id=tenant_id,
            run_id=agent.run_id,
            agent_id=agent.agent_id,
        )
        decision = await self._model_client.complete(
            ModelTurnInput(
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                agent_role=agent.role,
                objective=agent.objective,
                observations=restored_observations,
            )
        )
        await self._ensure_active(agent.run_id)
        if self._metrics_sink is not None:
            self._metrics_sink.record_agent_decision(kind=decision.kind.value)
        emit_structured_log(
            self._runtime_logger,
            "agent decision recorded",
            component="orchestrator",
            context={
                **get_request_context(),
                "tenant_id": tenant_id,
                "run_id": agent.run_id,
                "agent_id": agent.agent_id,
            },
            fields={"decision_kind": decision.kind.value},
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.AGENT_REASONED,
                payload=decision.model_dump(mode="json"),
            )
        )

        if decision.kind == DecisionKind.FINISH:
            return await self._finish_agent(
                tenant_id=tenant_id,
                agent=agent,
                decision=decision,
                restored_observations=restored_observations,
            )

        if decision.kind == DecisionKind.CALL_TOOL:
            return await self._call_tool_from_agent(
                tenant_id=tenant_id,
                agent=agent,
                decision=decision,
                restored_observations=restored_observations,
            )

        return await self._delegate_from_agent(
            tenant_id=tenant_id,
            agent=agent,
            decision=decision,
            restored_observations=restored_observations,
        )

    async def fail_run(self, run_id: str, error: str) -> None:
        run = await self._repository.get_run(run_id)
        if run is None or run.status in {RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.FAILED}:
            return

        agents = await self._repository.list_agents(run_id)
        failure_event = RuntimeEvent.build(
            tenant_id=run.tenant_id,
            run_id=run_id,
            agent_id=agents[0].agent_id if agents else None,
            event_type=EventType.RUN_FAILED,
            payload={"error": error},
        )
        await self._repository.mark_run_failed(
            run_id=run_id,
            error=error,
            event=failure_event,
            failed_agent_id=agents[0].agent_id if agents else None,
        )
        await self._event_hub.publish(failure_event)

    async def _emit(self, event: RuntimeEvent) -> None:
        await self._repository.append_event(event)
        await self._event_hub.publish(event)

    async def _require_active_run(self, run_id: str) -> RunRecord:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        if run.status == RunStatus.CANCELLED:
            raise RunCancelledError(run_id)
        if run.status == RunStatus.WAITING_FOR_APPROVAL:
            raise RuntimeError(f"run awaiting approval: {run_id}")
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            raise RuntimeError(f"run is not resumable: {run_id}")
        return run

    async def _ensure_active(self, run_id: str) -> None:
        await self._require_active_run(run_id)

    async def _get_supervisor(self, run_id: str) -> AgentRecord:
        agents = await self._repository.list_agents(run_id)
        if not agents:
            raise RuntimeError(f"supervisor not found for run: {run_id}")
        return agents[0]

    async def _require_agent(self, agent_id: str) -> AgentRecord:
        agent = await self._repository.get_agent(agent_id)
        if agent is None:
            raise RuntimeError(f"agent not found: {agent_id}")
        return agent

    def _restore_observations(
        self,
        supervisor: AgentRecord,
        latest_checkpoint: CheckpointRecord | None,
    ) -> list[str]:
        if latest_checkpoint is None:
            return supervisor.observations

        observations = latest_checkpoint.payload.get("observations")
        if not isinstance(observations, list):
            return supervisor.observations
        return [str(item) for item in observations]

    async def _finish_agent(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        decision: ModelDecision,
        restored_observations: list[str],
    ) -> str:
        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.COMPLETED,
        )
        completed_checkpoint = CheckpointRecord(
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            step_name="completed",
            payload={
                "result": decision.final_output,
                "observations": restored_observations,
            },
        )
        await self._repository.save_checkpoint(completed_checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": completed_checkpoint.step_name},
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.AGENT_COMPLETED,
                payload={"final_output": decision.final_output},
            )
        )

        if agent.role == AgentRole.SUPERVISOR:
            await self._ensure_active(agent.run_id)
            await self._repository.update_run_status(
                agent.run_id,
                RunStatus.COMPLETED,
                result=decision.final_output,
            )
            await self._emit(
                RuntimeEvent.build(
                    tenant_id=tenant_id,
                    run_id=agent.run_id,
                    event_type=EventType.RUN_COMPLETED,
                    payload={"result": decision.final_output},
                )
            )

        return decision.final_output or ""

    async def _delegate_from_agent(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        decision: ModelDecision,
        restored_observations: list[str],
    ) -> str:
        if agent.role != AgentRole.SUPERVISOR:
            raise RuntimeError(f"agent role does not support delegation: {agent.role.value}")

        worker_role = ensure_predefined_worker(decision.worker_role)
        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.WAITING_ON_WORKERS,
        )

        worker = AgentRecord(
            run_id=agent.run_id,
            role=worker_role,
            status=AgentStatus.READY,
            objective=decision.task_input or "",
            parent_agent_id=agent.agent_id,
        )
        task = TaskRecord(
            run_id=agent.run_id,
            parent_agent_id=agent.agent_id,
            worker_agent_id=worker.agent_id,
            worker_role=worker.role,
            objective=decision.task_input or "",
        )

        await self._repository.add_agent(worker)
        await self._repository.add_task(task)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.TASK_DISPATCHED,
                payload={
                    "task_id": task.task_id,
                    "worker_role": worker.role.value,
                    "objective": worker.objective,
                },
            )
        )
        dispatch_checkpoint = CheckpointRecord(
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            step_name="after_dispatch",
            payload={
                "observations": restored_observations,
                "task_id": task.task_id,
                "worker_agent_id": worker.agent_id,
            },
        )
        await self._repository.save_checkpoint(dispatch_checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": dispatch_checkpoint.step_name},
            )
        )

        worker_result = await self._run_agent(tenant_id, worker.agent_id)
        return await self._merge_worker_result_and_continue(
            tenant_id=tenant_id,
            agent=agent,
            task=task,
            worker=worker,
            worker_result=worker_result,
            restored_observations=restored_observations,
        )

    async def _resume_existing_dispatch_if_present(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        latest_checkpoint: CheckpointRecord | None,
        restored_observations: list[str],
    ) -> str | None:
        if agent.role != AgentRole.SUPERVISOR:
            return None
        if latest_checkpoint is None or latest_checkpoint.step_name != "after_dispatch":
            return None

        task, worker = await self._load_dispatched_work(agent, latest_checkpoint)
        if task is None or worker is None:
            return None

        if task.status == TaskStatus.COMPLETED:
            worker_result = task.result or await self._load_completed_worker_result(worker)
        else:
            if worker.status == AgentStatus.COMPLETED:
                worker_result = await self._load_completed_worker_result(worker)
            else:
                worker_result = await self._run_agent(tenant_id, worker.agent_id)

        return await self._merge_worker_result_and_continue(
            tenant_id=tenant_id,
            agent=agent,
            task=task,
            worker=worker,
            worker_result=worker_result,
            restored_observations=restored_observations,
        )

    async def _load_dispatched_work(
        self,
        agent: AgentRecord,
        latest_checkpoint: CheckpointRecord,
    ) -> tuple[TaskRecord | None, AgentRecord | None]:
        task_id = latest_checkpoint.payload.get("task_id")
        worker_agent_id = latest_checkpoint.payload.get("worker_agent_id")

        task = await self._repository.get_task(str(task_id)) if task_id else None
        worker = await self._repository.get_agent(str(worker_agent_id)) if worker_agent_id else None

        if task is not None and worker is not None:
            return task, worker

        tasks = await self._repository.list_tasks(agent.run_id)
        fallback_task = next(
            (item for item in tasks if item.parent_agent_id == agent.agent_id and item.status != TaskStatus.FAILED),
            None,
        )
        if fallback_task is None:
            return None, None

        fallback_worker = await self._repository.get_agent(fallback_task.worker_agent_id)
        return fallback_task, fallback_worker

    async def _load_completed_worker_result(self, worker: AgentRecord) -> str:
        latest_checkpoint = await self._repository.get_latest_checkpoint(worker.run_id, worker.agent_id)
        if latest_checkpoint is not None and latest_checkpoint.step_name == "completed":
            result = latest_checkpoint.payload.get("result")
            if isinstance(result, str):
                return result
        raise RuntimeError(f"completed worker result missing for agent: {worker.agent_id}")

    async def _merge_worker_result_and_continue(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        task: TaskRecord,
        worker: AgentRecord,
        worker_result: str,
        restored_observations: list[str],
    ) -> str:
        merged_entry = f"{worker.role.value}:{worker_result}"
        merged_observations = list(restored_observations)
        if merged_entry not in merged_observations:
            merged_observations.append(merged_entry)

        if task.status != TaskStatus.COMPLETED or task.result != worker_result:
            await self._repository.update_task_state(
                task.task_id,
                status=TaskStatus.COMPLETED,
                result=worker_result,
            )

        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.READY,
            observations=merged_observations,
        )
        merge_checkpoint = CheckpointRecord(
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            step_name="after_worker_merge",
            payload={"observations": merged_observations},
        )
        await self._repository.save_checkpoint(merge_checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": merge_checkpoint.step_name},
            )
        )
        return await self._run_agent(tenant_id, agent.agent_id)

    async def _resume_waiting_tool_if_present(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        latest_checkpoint: CheckpointRecord | None,
        restored_observations: list[str],
    ) -> str | None:
        if latest_checkpoint is None or latest_checkpoint.step_name != "waiting_for_approval":
            return None
        if self._tool_gateway is None:
            raise RuntimeError("tool gateway not configured")

        approval_id = latest_checkpoint.payload.get("approval_id")
        invocation_id = latest_checkpoint.payload.get("invocation_id")
        tool_name = latest_checkpoint.payload.get("tool_name")
        if not isinstance(approval_id, str) or not isinstance(invocation_id, str) or not isinstance(tool_name, str):
            raise RuntimeError(f"waiting-for-approval checkpoint is incomplete for agent: {agent.agent_id}")

        approval = await self._repository.get_approval_request(approval_id)
        if approval is None:
            raise RuntimeError(f"approval request not found: {approval_id}")
        if approval.status != ApprovalStatus.APPROVED:
            raise RuntimeError(f"approval is not approved: {approval_id}")

        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.WAITING_ON_TOOL,
            observations=restored_observations,
        )
        self._fault_injector.trigger(
            FaultPoint.TOOL_BEFORE_RESUME,
            tenant_id=tenant_id,
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            tool_name=tool_name,
        )
        started = time.perf_counter()
        outcome = await self._tool_gateway.resume_approved_invocation(invocation_id)
        if self._metrics_sink is not None:
            self._metrics_sink.record_tool_call(
                tool_name=tool_name,
                status=outcome.status.value,
                duration_seconds=time.perf_counter() - started,
            )
        return await self._complete_tool_call(
            tenant_id=tenant_id,
            agent=agent,
            restored_observations=restored_observations,
            tool_name=tool_name,
            invocation_id=outcome.invocation_id,
            result=outcome.result or {},
        )

    async def _complete_tool_call(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        restored_observations: list[str],
        tool_name: str,
        invocation_id: str,
        result: dict[str, object],
    ) -> str:
        tool_observation = f"{tool_name}:{result}"
        merged_observations = [*restored_observations, tool_observation]
        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.READY,
            observations=merged_observations,
        )
        checkpoint = CheckpointRecord(
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            step_name="after_tool_completed",
            payload={"observations": merged_observations, "invocation_id": invocation_id},
        )
        await self._repository.save_checkpoint(checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": checkpoint.step_name},
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.TOOL_COMPLETED,
                payload={
                    "tool_name": tool_name,
                    "invocation_id": invocation_id,
                    "result": result,
                },
            )
        )
        return await self._run_agent(tenant_id, agent.agent_id)

    async def _call_tool_from_agent(
        self,
        *,
        tenant_id: str,
        agent: AgentRecord,
        decision: ModelDecision,
        restored_observations: list[str],
    ) -> str:
        if self._tool_gateway is None:
            raise RuntimeError("tool gateway not configured")

        await self._repository.update_agent_state(
            agent.agent_id,
            status=AgentStatus.WAITING_ON_TOOL,
        )
        self._fault_injector.trigger(
            FaultPoint.TOOL_BEFORE_EXECUTE,
            tenant_id=tenant_id,
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            tool_name=decision.tool_name or "",
        )
        started = time.perf_counter()
        outcome = await self._tool_gateway.execute(
            ToolExecutionRequest(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                tool_name=decision.tool_name or "",
                arguments=decision.tool_arguments or {},
            )
        )
        if self._metrics_sink is not None:
            self._metrics_sink.record_tool_call(
                tool_name=decision.tool_name or "",
                status=outcome.status.value,
                duration_seconds=time.perf_counter() - started,
            )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.TOOL_CALLED,
                payload={
                    "tool_name": decision.tool_name,
                    "arguments": decision.tool_arguments or {},
                    "invocation_id": outcome.invocation_id,
                },
            )
        )

        if outcome.requires_approval:
            await self._repository.update_agent_state(
                agent.agent_id,
                status=AgentStatus.WAITING_FOR_APPROVAL,
            )
            await self._repository.update_run_status(
                agent.run_id,
                RunStatus.WAITING_FOR_APPROVAL,
            )
            checkpoint = CheckpointRecord(
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                step_name="waiting_for_approval",
                payload={
                    "observations": restored_observations,
                    "tool_name": decision.tool_name,
                    "tool_arguments": decision.tool_arguments or {},
                    "invocation_id": outcome.invocation_id,
                    "approval_id": outcome.approval_id,
                },
            )
            await self._repository.save_checkpoint(checkpoint)
            await self._emit(
                RuntimeEvent.build(
                    tenant_id=tenant_id,
                    run_id=agent.run_id,
                    agent_id=agent.agent_id,
                    event_type=EventType.CHECKPOINT_CREATED,
                    payload={"step_name": checkpoint.step_name},
                )
            )
            await self._emit(
                RuntimeEvent.build(
                    tenant_id=tenant_id,
                    run_id=agent.run_id,
                    agent_id=agent.agent_id,
                    event_type=EventType.APPROVAL_REQUESTED,
                    payload={
                        "approval_id": outcome.approval_id,
                        "tool_name": decision.tool_name,
                        "invocation_id": outcome.invocation_id,
                    },
                )
            )
            return ""

        return await self._complete_tool_call(
            tenant_id=tenant_id,
            agent=agent,
            restored_observations=restored_observations,
            tool_name=decision.tool_name or "",
            invocation_id=outcome.invocation_id,
            result=outcome.result or {},
        )
