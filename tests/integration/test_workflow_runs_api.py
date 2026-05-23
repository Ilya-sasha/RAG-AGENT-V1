from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import AgentRole, AgentStatus, ApprovalStatus, RunStatus, TaskStatus
from agent_runtime.domain.models import (
    AgentRecord,
    ApprovalRequestRecord,
    CheckpointRecord,
    RunRecord,
    TaskRecord,
    WorkflowRunLinkRecord,
    WorkflowTemplateRecord,
    WorkflowTemplateVersionRecord,
)
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.workflows.repository import WorkflowRepository
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


def _workflow_definition() -> dict[str, object]:
    return {
        "entrypoint": {
            "objective_template": "Investigate incident {ticket_id}",
            "result_contract": "string",
        },
        "agents": {
            "allowed_worker_roles": ["researcher"],
            "max_worker_count": 1,
        },
        "tools": {
            "allowed_tools": ["rag_search"],
            "approval_required_tools": [],
        },
        "knowledge": {
            "default_kb_ids": [],
            "allow_kb_override": False,
        },
        "runtime": {
            "max_turns": 8,
            "timeout_seconds": 600,
            "tags": ["ops"],
        },
        "launch_policy": {
            "allow_input_objective_override": False,
            "require_published_version": True,
        },
    }


def _workflow_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"ticket_id": {"type": "string"}},
        "required": ["ticket_id"],
    }


async def _seed_workflow_template(
    app,
    *,
    tenant_id: str,
    workflow_id: str,
    workflow_name: str,
    created_at: datetime,
) -> None:
    await WorkflowRepository(app.state.session_factory).create_template(
        WorkflowTemplateRecord(
            template_id=workflow_id,
            tenant_id=tenant_id,
            name=workflow_name,
            description=f"{workflow_name} description",
            status="draft",
            latest_version=1,
            latest_published_version=1,
            created_at=created_at,
            updated_at=created_at,
        ),
        WorkflowTemplateVersionRecord(
            template_id=workflow_id,
            version=1,
            definition=_workflow_definition(),
            input_schema=_workflow_input_schema(),
            is_published=True,
            published_at=created_at,
            created_at=created_at,
            created_by="operator-a",
        ),
    )


async def _seed_workflow_linked_run(
    app,
    *,
    run_id: str,
    tenant_id: str,
    workflow_id: str,
    workflow_name: str,
    template_version: int,
    created_at: datetime,
    status: RunStatus,
    add_worker_task: bool = False,
    add_checkpoint: bool = False,
    add_pending_approval: bool = False,
    worker_checkpoint_step: str | None = None,
) -> None:
    objective = f"Investigate {run_id}"
    supervisor_agent_id = f"agent-{run_id}"
    runtime_repository = RuntimeRepository(app.state.session_factory)
    workflow_repository = WorkflowRepository(app.state.session_factory)
    await runtime_repository.create_run(
        RunRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            objective=objective,
            created_at=created_at,
            updated_at=created_at,
        ),
        AgentRecord(
            agent_id=supervisor_agent_id,
            run_id=run_id,
            role=AgentRole.SUPERVISOR,
            status=AgentStatus.READY,
            objective=objective,
            created_at=created_at,
            updated_at=created_at,
        ),
    )
    await workflow_repository.create_run_link(
        WorkflowRunLinkRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            template_id=workflow_id,
            template_version=template_version,
            template_name=workflow_name,
            launch_input={"ticket_id": run_id},
            launch_metadata={"requested_by": "operator-a"},
            effective_workflow_policy={"allowed_tools": ["rag_search"]},
            created_at=created_at,
        )
    )

    if add_worker_task:
        worker_agent_id = f"worker-{run_id}"
        task_id = f"task-{run_id}"
        await runtime_repository.add_agent(
            AgentRecord(
                agent_id=worker_agent_id,
                run_id=run_id,
                role=AgentRole.RESEARCHER,
                status=AgentStatus.REASONING,
                objective=f"Research {run_id}",
                parent_agent_id=supervisor_agent_id,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await runtime_repository.add_task(
            TaskRecord(
                task_id=task_id,
                run_id=run_id,
                parent_agent_id=supervisor_agent_id,
                worker_agent_id=worker_agent_id,
                worker_role=AgentRole.RESEARCHER,
                objective=f"Research {run_id}",
                status=TaskStatus.RUNNING,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        if worker_checkpoint_step is not None:
            await runtime_repository.save_checkpoint(
                CheckpointRecord(
                    checkpoint_id=f"worker-checkpoint-{run_id}",
                    run_id=run_id,
                    agent_id=worker_agent_id,
                    step_name=worker_checkpoint_step,
                    payload={"ticket_id": run_id, "worker": worker_agent_id},
                    created_at=created_at + timedelta(seconds=3),
                )
            )

    if add_checkpoint:
        await runtime_repository.save_checkpoint(
            CheckpointRecord(
                checkpoint_id=f"checkpoint-{run_id}",
                run_id=run_id,
                agent_id=supervisor_agent_id,
                step_name="collect-evidence",
                payload={"ticket_id": run_id},
                created_at=created_at + timedelta(seconds=1),
            )
        )

    if add_pending_approval:
        await runtime_repository.create_approval_request(
            ApprovalRequestRecord(
                approval_id=f"approval-{run_id}",
                tenant_id=tenant_id,
                run_id=run_id,
                agent_id=supervisor_agent_id,
                tool_name="rag_search",
                reason="Need KB access",
                status=ApprovalStatus.PENDING,
                created_at=created_at + timedelta(seconds=2),
                updated_at=created_at + timedelta(seconds=2),
            )
        )

    await runtime_repository.update_run_status(run_id, status)


async def _seed_plain_run(
    app,
    *,
    run_id: str,
    tenant_id: str,
    created_at: datetime,
) -> None:
    objective = f"Plain runtime objective for {run_id}"
    await RuntimeRepository(app.state.session_factory).create_run(
        RunRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            objective=objective,
            created_at=created_at,
            updated_at=created_at,
        ),
        AgentRecord(
            agent_id=f"agent-{run_id}",
            run_id=run_id,
            role=AgentRole.SUPERVISOR,
            objective=objective,
            created_at=created_at,
            updated_at=created_at,
        ),
    )


@pytest.mark.asyncio
async def test_workflow_run_list_returns_items_and_next_cursor(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        created_at = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
        await _seed_workflow_template(
            app,
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            created_at=created_at,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-newest",
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            template_version=1,
            created_at=created_at + timedelta(minutes=2),
            status=RunStatus.RUNNING,
            add_worker_task=True,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-older",
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            template_version=1,
            created_at=created_at + timedelta(minutes=1),
            status=RunStatus.COMPLETED,
        )

        response = await client.get(
            "/v1/workflow-runs",
            params={"tenant_id": "tenant-a", "limit": 1},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"] == [
            {
                "run_id": "run-newest",
                "tenant_id": "tenant-a",
                "workflow_id": "wf-triage",
                "workflow_name": "Incident Triage",
                "template_version": 1,
                "status": "running",
                "current_blocking_state": "waiting_on_worker",
                "current_blocking_state_reason": "1 running task(s)",
                "latest_failure_summary": None,
                "latest_checkpoint_step": None,
                "started_at": payload["items"][0]["started_at"],
                "last_updated_at": payload["items"][0]["last_updated_at"],
                "pending_approval": None,
            }
        ]
        assert isinstance(payload["next_cursor"], str)


@pytest.mark.asyncio
async def test_workflow_run_list_trims_tenant_id_and_applies_filters_and_cursor(
    tmp_path: Path,
) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        created_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        await _seed_workflow_template(
            app,
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            created_at=created_at,
        )
        await _seed_workflow_template(
            app,
            tenant_id="tenant-a",
            workflow_id="wf-review",
            workflow_name="Review Queue",
            created_at=created_at,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-completed",
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            template_version=1,
            created_at=created_at + timedelta(minutes=1),
            status=RunStatus.COMPLETED,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-match",
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            template_version=1,
            created_at=created_at + timedelta(minutes=2),
            status=RunStatus.RUNNING,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-other-workflow",
            tenant_id="tenant-a",
            workflow_id="wf-review",
            workflow_name="Review Queue",
            template_version=1,
            created_at=created_at + timedelta(minutes=3),
            status=RunStatus.RUNNING,
        )

        filtered_response = await client.get(
            "/v1/workflow-runs",
            params={
                "tenant_id": "  tenant-a  ",
                "workflow_id": "wf-triage",
                "template_version": 1,
                "status": "running",
                "created_after": (created_at + timedelta(minutes=1, seconds=30)).isoformat(),
                "created_before": (created_at + timedelta(minutes=2, seconds=30)).isoformat(),
            },
        )

        assert filtered_response.status_code == 200
        filtered_payload = filtered_response.json()
        assert filtered_payload == {
            "items": [
                {
                    "run_id": "run-match",
                    "tenant_id": "tenant-a",
                    "workflow_id": "wf-triage",
                    "workflow_name": "Incident Triage",
                    "template_version": 1,
                    "status": "running",
                    "current_blocking_state": "running",
                    "current_blocking_state_reason": None,
                    "latest_failure_summary": None,
                    "latest_checkpoint_step": None,
                    "started_at": filtered_payload["items"][0]["started_at"],
                    "last_updated_at": filtered_payload["items"][0]["last_updated_at"],
                    "pending_approval": None,
                }
            ],
            "next_cursor": None,
        }

        first_page_response = await client.get(
            "/v1/workflow-runs",
            params={"tenant_id": "tenant-a", "limit": 1},
        )
        assert first_page_response.status_code == 200
        first_page_payload = first_page_response.json()
        assert [item["run_id"] for item in first_page_payload["items"]] == ["run-other-workflow"]
        assert isinstance(first_page_payload["next_cursor"], str)

        second_page_response = await client.get(
            "/v1/workflow-runs",
            params={
                "tenant_id": "tenant-a",
                "limit": 1,
                "cursor": first_page_payload["next_cursor"],
            },
        )
        assert second_page_response.status_code == 200
        second_page_payload = second_page_response.json()
        assert [item["run_id"] for item in second_page_payload["items"]] == ["run-match"]
        assert isinstance(second_page_payload["next_cursor"], str)


@pytest.mark.asyncio
async def test_workflow_run_detail_returns_expected_shape_for_workflow_linked_run(
    tmp_path: Path,
) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        created_at = datetime(2026, 1, 3, 10, 0, tzinfo=UTC)
        await _seed_workflow_template(
            app,
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            created_at=created_at,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-detail",
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            template_version=1,
            created_at=created_at + timedelta(minutes=5),
            status=RunStatus.RUNNING,
            add_worker_task=True,
            add_checkpoint=True,
            add_pending_approval=True,
            worker_checkpoint_step="before_model",
        )

        response = await client.get(
            "/v1/workflow-runs/run-detail",
            params={"tenant_id": "tenant-a"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {
            "run",
            "workflow",
            "agents",
            "tasks",
            "latest_checkpoint",
            "pending_approval",
            "current_blocking_state",
            "latest_failure_summary",
        }
        assert payload["workflow"] == {
            "workflow_id": "wf-triage",
            "workflow_name": "Incident Triage",
            "template_version": 1,
            "launch_input": {"ticket_id": "run-detail"},
            "launch_metadata": {"requested_by": "operator-a"},
        }
        assert payload["run"]["run_id"] == "run-detail"
        assert payload["run"]["tenant_id"] == "tenant-a"
        assert payload["run"]["status"] == "running"
        assert len(payload["agents"]) == 2
        assert len(payload["tasks"]) == 1
        assert payload["latest_checkpoint"]["agent_id"] == "agent-run-detail"
        assert payload["latest_checkpoint"]["step_name"] == "collect-evidence"
        assert payload["pending_approval"] == {
            "approval_id": "approval-run-detail",
            "agent_id": "agent-run-detail",
            "tool_name": "rag_search",
            "reason": "Need KB access",
            "created_at": payload["pending_approval"]["created_at"],
        }
        assert payload["current_blocking_state"] == "waiting_for_approval"
        assert payload["latest_failure_summary"] is None


@pytest.mark.asyncio
async def test_workflow_run_detail_rejects_plain_non_workflow_run(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        created_at = datetime(2026, 1, 4, 11, 0, tzinfo=UTC)
        await _seed_plain_run(
            app,
            run_id="plain-run",
            tenant_id="tenant-a",
            created_at=created_at,
        )

        response = await client.get(
            "/v1/workflow-runs/plain-run",
            params={"tenant_id": "tenant-a"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "workflow run not found: plain-run"}


@pytest.mark.asyncio
async def test_workflow_run_list_rejects_missing_tenant_id(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        response = await client.get("/v1/workflow-runs")

        assert response.status_code == 400
        assert response.json() == {"detail": "tenant_id is required"}


@pytest.mark.asyncio
async def test_workflow_run_list_rejects_invalid_status_and_datetime_inputs(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        invalid_status_response = await client.get(
            "/v1/workflow-runs",
            params={"tenant_id": "tenant-a", "status": "not-a-status"},
        )
        assert invalid_status_response.status_code == 400
        assert invalid_status_response.json() == {
            "detail": "status must be one of: created, running, waiting_for_approval, paused, failed, completed, cancelled"
        }

        invalid_datetime_response = await client.get(
            "/v1/workflow-runs",
            params={"tenant_id": "tenant-a", "created_after": "not-a-datetime"},
        )
        assert invalid_datetime_response.status_code == 400
        assert invalid_datetime_response.json() == {
            "detail": "created_after must be a timezone-aware ISO 8601 datetime"
        }

        naive_datetime_response = await client.get(
            "/v1/workflow-runs",
            params={"tenant_id": "tenant-a", "created_after": "2026-01-02T12:00:00"},
        )
        assert naive_datetime_response.status_code == 400
        assert naive_datetime_response.json() == {
            "detail": "created_after must be a timezone-aware ISO 8601 datetime"
        }


@pytest.mark.asyncio
async def test_workflow_run_list_uses_supervisor_checkpoint_for_latest_progress(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        created_at = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
        await _seed_workflow_template(
            app,
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            created_at=created_at,
        )
        await _seed_workflow_linked_run(
            app,
            run_id="run-supervisor-progress",
            tenant_id="tenant-a",
            workflow_id="wf-triage",
            workflow_name="Incident Triage",
            template_version=1,
            created_at=created_at + timedelta(minutes=1),
            status=RunStatus.RUNNING,
            add_worker_task=True,
            add_checkpoint=True,
            worker_checkpoint_step="before_model",
        )

        response = await client.get(
            "/v1/workflow-runs",
            params={"tenant_id": "tenant-a"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["run_id"] == "run-supervisor-progress"
        assert payload["items"][0]["latest_checkpoint_step"] == "collect-evidence"
