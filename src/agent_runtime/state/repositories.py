from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.domain.enums import (
    AgentRole,
    AgentStatus,
    ApprovalStatus,
    EventType,
    RunStatus,
    TaskStatus,
    ToolInvocationStatus,
)
from agent_runtime.domain.models import (
    AgentRecord,
    ApprovalRequestRecord,
    CheckpointRecord,
    RunRecord,
    RuntimeEvent,
    TaskRecord,
    TenantPolicyRecord,
    ToolDefinitionRecord,
    ToolInvocationRecord,
)
from agent_runtime.state.tables import (
    AgentTable,
    ApprovalRequestTable,
    CheckpointTable,
    EventTable,
    RunTable,
    TaskTable,
    TenantPolicyTable,
    ToolDefinitionTable,
    ToolInvocationTable,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run(self, run: RunRecord, supervisor: AgentRecord) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    RunTable(
                        run_id=run.run_id,
                        tenant_id=run.tenant_id,
                        objective=run.objective,
                        status=run.status.value,
                        result=run.result,
                        error=run.error,
                        created_at=run.created_at,
                        updated_at=run.updated_at,
                    )
                )
                await session.flush()
                session.add(
                    AgentTable(
                        agent_id=supervisor.agent_id,
                        run_id=supervisor.run_id,
                        role=supervisor.role.value,
                        status=supervisor.status.value,
                        objective=supervisor.objective,
                        observations=supervisor.observations,
                        parent_agent_id=supervisor.parent_agent_id,
                        task_id=supervisor.task_id,
                        created_at=supervisor.created_at,
                        updated_at=supervisor.updated_at,
                    )
                )

    async def append_event(self, event: RuntimeEvent) -> None:
        async with self._session_factory() as session:
            session.add(
                EventTable(
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    run_id=event.run_id,
                    agent_id=event.agent_id,
                    event_type=event.event_type.value,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )
            await session.commit()

    async def save_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                CheckpointTable(
                    checkpoint_id=checkpoint.checkpoint_id,
                    run_id=checkpoint.run_id,
                    agent_id=checkpoint.agent_id,
                    step_name=checkpoint.step_name,
                    payload=checkpoint.payload,
                    created_at=checkpoint.created_at,
                )
            )
            await session.commit()

    async def add_agent(self, agent: AgentRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                AgentTable(
                    agent_id=agent.agent_id,
                    run_id=agent.run_id,
                    role=agent.role.value,
                    status=agent.status.value,
                    objective=agent.objective,
                    observations=agent.observations,
                    parent_agent_id=agent.parent_agent_id,
                    task_id=agent.task_id,
                    created_at=agent.created_at,
                    updated_at=agent.updated_at,
                )
            )
            await session.commit()

    async def add_task(self, task: TaskRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                TaskTable(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    parent_agent_id=task.parent_agent_id,
                    worker_agent_id=task.worker_agent_id,
                    worker_role=task.worker_role.value,
                    objective=task.objective,
                    status=task.status.value,
                    result=task.result,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )
            await session.commit()

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._session_factory() as session:
            row = await session.get(RunTable, run_id)
            if row is None:
                return None
            return RunRecord(
                run_id=row.run_id,
                tenant_id=row.tenant_id,
                objective=row.objective,
                status=RunStatus(row.status),
                result=row.result,
                error=row.error,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        async with self._session_factory() as session:
            row = await session.get(AgentTable, agent_id)
            if row is None:
                return None
            return AgentRecord(
                agent_id=row.agent_id,
                run_id=row.run_id,
                role=AgentRole(row.role),
                status=AgentStatus(row.status),
                objective=row.objective,
                observations=row.observations,
                parent_agent_id=row.parent_agent_id,
                task_id=row.task_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def list_agents(self, run_id: str) -> list[AgentRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AgentTable)
                    .where(AgentTable.run_id == run_id)
                    .order_by(AgentTable.created_at, AgentTable.agent_id)
                )
            ).scalars()
            return [
                AgentRecord(
                    agent_id=row.agent_id,
                    run_id=row.run_id,
                    role=AgentRole(row.role),
                    status=AgentStatus(row.status),
                    objective=row.objective,
                    observations=row.observations,
                    parent_agent_id=row.parent_agent_id,
                    task_id=row.task_id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def list_events(self, run_id: str) -> list[RuntimeEvent]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(EventTable)
                    .where(EventTable.run_id == run_id)
                    .order_by(EventTable.created_at, EventTable.event_id)
                )
            ).scalars()
            return [
                RuntimeEvent(
                    event_id=row.event_id,
                    tenant_id=row.tenant_id,
                    run_id=row.run_id,
                    event_type=EventType(row.event_type),
                    payload=row.payload,
                    agent_id=row.agent_id,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    async def list_tasks(self, run_id: str) -> list[TaskRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(TaskTable)
                    .where(TaskTable.run_id == run_id)
                    .order_by(TaskTable.created_at, TaskTable.task_id)
                )
            ).scalars()
            return [
                TaskRecord(
                    task_id=row.task_id,
                    run_id=row.run_id,
                    parent_agent_id=row.parent_agent_id,
                    worker_agent_id=row.worker_agent_id,
                    worker_role=AgentRole(row.worker_role),
                    objective=row.objective,
                    status=TaskStatus(row.status),
                    result=row.result,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with self._session_factory() as session:
            row = await session.get(TaskTable, task_id)
            if row is None:
                return None
            return TaskRecord(
                task_id=row.task_id,
                run_id=row.run_id,
                parent_agent_id=row.parent_agent_id,
                worker_agent_id=row.worker_agent_id,
                worker_role=AgentRole(row.worker_role),
                objective=row.objective,
                status=TaskStatus(row.status),
                result=row.result,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def get_latest_checkpoint(self, run_id: str, agent_id: str) -> CheckpointRecord | None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(CheckpointTable)
                    .where(CheckpointTable.run_id == run_id, CheckpointTable.agent_id == agent_id)
                    .order_by(CheckpointTable.created_at.desc(), CheckpointTable.checkpoint_id.desc())
                    .limit(1)
                )
            ).scalars().all()
            if not rows:
                return None

            row = rows[0]
            return CheckpointRecord(
                checkpoint_id=row.checkpoint_id,
                run_id=row.run_id,
                agent_id=row.agent_id,
                step_name=row.step_name,
                payload=row.payload,
                created_at=row.created_at,
            )

    async def get_latest_checkpoint_by_run_id(
        self,
        run_id: str,
        *,
        agent_role: AgentRole | None = None,
    ) -> CheckpointRecord | None:
        async with self._session_factory() as session:
            query = select(CheckpointTable).where(CheckpointTable.run_id == run_id)
            if agent_role is not None:
                query = query.join(
                    AgentTable,
                    and_(
                        AgentTable.agent_id == CheckpointTable.agent_id,
                        AgentTable.run_id == CheckpointTable.run_id,
                    ),
                ).where(AgentTable.role == agent_role.value)
            rows = (
                await session.execute(
                    query
                    .order_by(CheckpointTable.created_at.desc(), CheckpointTable.checkpoint_id.desc())
                    .limit(1)
                )
            ).scalars().all()
            if not rows:
                return None

            row = rows[0]
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
            rows = (
                await session.execute(
                    select(EventTable)
                    .where(
                        EventTable.run_id == run_id,
                        EventTable.event_type == EventType.RUN_FAILED.value,
                    )
                    .order_by(EventTable.created_at.desc(), EventTable.event_id.desc())
                    .limit(1)
                )
            ).scalars().all()
            if not rows:
                return None

            row = rows[0]
            return RuntimeEvent(
                event_id=row.event_id,
                tenant_id=row.tenant_id,
                run_id=row.run_id,
                event_type=EventType(row.event_type),
                payload=row.payload,
                agent_id=row.agent_id,
                created_at=row.created_at,
            )

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(RunTable, run_id)
            if row is None:
                raise RuntimeError(f"run not found: {run_id}")
            current_status = RunStatus(row.status)
            terminal_statuses = {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }
            if current_status in terminal_statuses and current_status != status:
                return
            row.status = status.value
            row.result = result
            row.error = error
            row.updated_at = utc_now()
            await session.commit()

    async def mark_run_failed(
        self,
        *,
        run_id: str,
        error: str,
        event: RuntimeEvent,
        failed_agent_id: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            run_row = await session.get(RunTable, run_id)
            if run_row is None:
                raise RuntimeError(f"run not found: {run_id}")

            current_status = RunStatus(run_row.status)
            terminal_statuses = {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }
            if current_status in terminal_statuses:
                return

            if failed_agent_id is not None:
                agent_row = await session.get(AgentTable, failed_agent_id)
                if agent_row is None:
                    raise RuntimeError(f"agent not found: {failed_agent_id}")
                agent_row.status = AgentStatus.FAILED.value
                agent_row.updated_at = utc_now()

            run_row.status = RunStatus.FAILED.value
            run_row.result = None
            run_row.error = error
            run_row.updated_at = utc_now()

            session.add(
                EventTable(
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    run_id=event.run_id,
                    agent_id=event.agent_id,
                    event_type=event.event_type.value,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )
            await session.commit()

    async def update_agent_state(
        self,
        agent_id: str,
        *,
        status: AgentStatus | None = None,
        observations: list[str] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(AgentTable, agent_id)
            if row is None:
                raise RuntimeError(f"agent not found: {agent_id}")
            if status is not None:
                row.status = status.value
            if observations is not None:
                row.observations = observations
            row.updated_at = utc_now()
            await session.commit()

    async def update_task_state(self, task_id: str, *, status: TaskStatus, result: str | None = None) -> None:
        async with self._session_factory() as session:
            row = await session.get(TaskTable, task_id)
            if row is None:
                raise RuntimeError(f"task not found: {task_id}")
            row.status = status.value
            row.result = result
            row.updated_at = utc_now()
            await session.commit()

    async def list_active_runs(self) -> list[RunRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(RunTable).where(
                        RunTable.status.in_(
                            [
                                RunStatus.CREATED.value,
                                RunStatus.RUNNING.value,
                                RunStatus.PAUSED.value,
                            ]
                        )
                    ).order_by(RunTable.created_at, RunTable.run_id)
                )
            ).scalars()
            return [
                RunRecord(
                    run_id=row.run_id,
                    tenant_id=row.tenant_id,
                    objective=row.objective,
                    status=RunStatus(row.status),
                    result=row.result,
                    error=row.error,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def upsert_tenant_policy(self, policy: TenantPolicyRecord) -> None:
        async with self._session_factory() as session:
            row = await session.get(TenantPolicyTable, policy.tenant_id)
            if row is None:
                session.add(
                    TenantPolicyTable(
                        tenant_id=policy.tenant_id,
                        allowed_tools=policy.allowed_tools,
                        approval_required_tools=policy.approval_required_tools,
                        created_at=policy.created_at,
                        updated_at=policy.updated_at,
                    )
                )
            else:
                row.allowed_tools = policy.allowed_tools
                row.approval_required_tools = policy.approval_required_tools
                row.updated_at = utc_now()
            await session.commit()

    async def get_tenant_policy(self, tenant_id: str) -> TenantPolicyRecord | None:
        async with self._session_factory() as session:
            row = await session.get(TenantPolicyTable, tenant_id)
            if row is None:
                return None
            return TenantPolicyRecord(
                tenant_id=row.tenant_id,
                allowed_tools=row.allowed_tools,
                approval_required_tools=row.approval_required_tools,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def upsert_tool_definition(self, tool: ToolDefinitionRecord) -> None:
        async with self._session_factory() as session:
            row = await session.get(ToolDefinitionTable, tool.tool_name)
            if row is None:
                session.add(
                    ToolDefinitionTable(
                        tool_name=tool.tool_name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                        requires_approval=tool.requires_approval,
                        created_at=tool.created_at,
                        updated_at=tool.updated_at,
                    )
                )
            else:
                row.description = tool.description
                row.input_schema = tool.input_schema
                row.requires_approval = tool.requires_approval
                row.updated_at = utc_now()
            await session.commit()

    async def get_tool_definition(self, tool_name: str) -> ToolDefinitionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(ToolDefinitionTable, tool_name)
            if row is None:
                return None
            return ToolDefinitionRecord(
                tool_name=row.tool_name,
                description=row.description,
                input_schema=row.input_schema,
                requires_approval=row.requires_approval,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def create_approval_request(self, approval: ApprovalRequestRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                ApprovalRequestTable(
                    approval_id=approval.approval_id,
                    tenant_id=approval.tenant_id,
                    run_id=approval.run_id,
                    agent_id=approval.agent_id,
                    tool_name=approval.tool_name,
                    reason=approval.reason,
                    status=approval.status.value,
                    resolution_note=approval.resolution_note,
                    created_at=approval.created_at,
                    updated_at=approval.updated_at,
                )
            )
            await session.commit()

    async def get_approval_request(self, approval_id: str) -> ApprovalRequestRecord | None:
        async with self._session_factory() as session:
            row = await session.get(ApprovalRequestTable, approval_id)
            if row is None:
                return None
            return ApprovalRequestRecord(
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

    async def list_pending_approvals_by_run_ids(
        self,
        run_ids: list[str],
    ) -> dict[str, list[ApprovalRequestRecord]]:
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
                    .order_by(
                        ApprovalRequestTable.created_at.asc(),
                        ApprovalRequestTable.approval_id.asc(),
                    )
                )
            ).scalars()

            approvals_by_run_id: dict[str, list[ApprovalRequestRecord]] = {}
            for row in rows:
                approvals_by_run_id.setdefault(row.run_id, []).append(
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
            return approvals_by_run_id

    async def update_approval_request(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        resolution_note: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(ApprovalRequestTable, approval_id)
            if row is None:
                raise RuntimeError(f"approval request not found: {approval_id}")
            row.status = status.value
            row.resolution_note = resolution_note
            row.updated_at = utc_now()
            await session.commit()

    async def create_tool_invocation(self, invocation: ToolInvocationRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                ToolInvocationTable(
                    invocation_id=invocation.invocation_id,
                    tenant_id=invocation.tenant_id,
                    run_id=invocation.run_id,
                    agent_id=invocation.agent_id,
                    tool_name=invocation.tool_name,
                    arguments=invocation.arguments,
                    status=invocation.status.value,
                    result=invocation.result,
                    error=invocation.error,
                    created_at=invocation.created_at,
                    updated_at=invocation.updated_at,
                )
            )
            await session.commit()

    async def get_tool_invocation(self, invocation_id: str) -> ToolInvocationRecord | None:
        async with self._session_factory() as session:
            row = await session.get(ToolInvocationTable, invocation_id)
            if row is None:
                return None
            return ToolInvocationRecord(
                invocation_id=row.invocation_id,
                tenant_id=row.tenant_id,
                run_id=row.run_id,
                agent_id=row.agent_id,
                tool_name=row.tool_name,
                arguments=row.arguments,
                status=ToolInvocationStatus(row.status),
                result=row.result,
                error=row.error,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def update_tool_invocation(
        self,
        invocation_id: str,
        *,
        status: ToolInvocationStatus,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(ToolInvocationTable, invocation_id)
            if row is None:
                raise RuntimeError(f"tool invocation not found: {invocation_id}")
            row.status = status.value
            row.result = result
            row.error = error
            row.updated_at = utc_now()
            await session.commit()
