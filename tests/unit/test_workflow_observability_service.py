from __future__ import annotations

import importlib

import pytest

from agent_runtime.domain.enums import AgentRole, RunStatus
from agent_runtime.domain.models import (
    AgentRecord,
    RunRecord,
    WorkflowRunLinkRecord,
    WorkflowTemplateRecord,
    WorkflowTemplateVersionRecord,
)
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository


def load_workflow_repository():
    module = importlib.import_module("agent_runtime.workflows.repository")
    return module.WorkflowRepository


def load_workflow_observability_module():
    return importlib.import_module("agent_runtime.workflows.observability")


async def _create_workflow_linked_run(
    *,
    runtime_repository: RuntimeRepository,
    workflow_repository,
    run_id: str,
    tenant_id: str,
    status: RunStatus,
    template_id: str = "wf-triage",
    template_version: int = 2,
) -> None:
    await runtime_repository.create_run(
        RunRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            objective=f"triage objective for {run_id}",
        ),
        AgentRecord(
            agent_id=f"agent-{run_id}",
            run_id=run_id,
            role=AgentRole.SUPERVISOR,
            objective=f"triage objective for {run_id}",
        ),
    )
    await runtime_repository.update_run_status(run_id, status)
    await workflow_repository.create_run_link(
        WorkflowRunLinkRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            template_id=template_id,
            template_version=template_version,
            template_name="Incident Triage",
            launch_input={"ticket_id": run_id},
            launch_metadata={"requested_by": "operator-a"},
            effective_workflow_policy={"allowed_tools": ["rag_search"]},
        )
    )


@pytest.mark.asyncio
async def test_list_workflow_run_summaries_filters_by_workflow_version_status_and_limit(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incident workflows",
                status="draft",
                latest_version=2,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=2,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )

        await _create_workflow_linked_run(
            runtime_repository=runtime_repository,
            workflow_repository=workflow_repository,
            run_id="run-1",
            tenant_id="tenant-a",
            status=RunStatus.FAILED,
        )
        await _create_workflow_linked_run(
            runtime_repository=runtime_repository,
            workflow_repository=workflow_repository,
            run_id="run-2",
            tenant_id="tenant-a",
            status=RunStatus.COMPLETED,
        )
        await _create_workflow_linked_run(
            runtime_repository=runtime_repository,
            workflow_repository=workflow_repository,
            run_id="run-3",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
        )
        summaries = await workflow_repository.list_workflow_run_summaries(
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            template_version=2,
            status=RunStatus.RUNNING,
            limit=1,
            cursor=None,
        )

        assert [item["run_id"] for item in summaries["items"]] == ["run-3"]
        assert summaries["next_cursor"] is None
    finally:
        await dispose_session_factory(session_factory)


def test_workflow_observability_service_derives_blocking_state_and_failure_summary() -> None:
    observability = load_workflow_observability_module()
    service = observability.WorkflowObservabilityService(
        workflow_repository=object(),
        runtime_repository=object(),
    )

    assert service._derive_observation_status(
        run_status="running",
        pending_approval_count=1,
        running_task_count=0,
    ) == "waiting_for_approval"
    assert service._derive_observation_status(
        run_status="running",
        pending_approval_count=0,
        running_task_count=1,
    ) == "waiting_on_worker"
    assert service._derive_failure_summary(
        run_error="tool timed out",
        latest_failure_event_error="ignored event error",
        latest_checkpoint_step="waiting_for_tool",
    ) == "tool timed out"


@pytest.mark.asyncio
async def test_workflow_observability_service_get_workflow_run_detail_rejects_plain_runtime_run(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        observability = load_workflow_observability_module()
        service = observability.WorkflowObservabilityService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
        )

        await runtime_repository.create_run(
            RunRecord(
                run_id="plain-run",
                tenant_id="tenant-a",
                objective="plain runtime run",
            ),
            AgentRecord(
                agent_id="agent-plain-run",
                run_id="plain-run",
                role=AgentRole.SUPERVISOR,
                objective="plain runtime run",
            ),
        )

        with pytest.raises(observability.WorkflowRunObservationNotFoundError, match="workflow run not found"):
            await service.get_workflow_run_detail(tenant_id="tenant-a", run_id="plain-run")
    finally:
        await dispose_session_factory(session_factory)
