from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.domain.models import WorkflowTemplateRecord, WorkflowTemplateVersionRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


def _workflow_definition() -> dict[str, object]:
    return {
        "entrypoint": {
            "objective_template": "Triage incident {ticket_id}",
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


async def _wait_for_run_status(client, run_id: str, status: str) -> dict[str, object]:
    for _ in range(20):
        response = await client.get(f"/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    return payload


async def _seed_workflow(
    app,
    *,
    workflow_id: str,
    tenant_id: str,
    name: str,
    created_at: datetime,
) -> None:
    await app.state.workflow_service.repository.create_template(
        WorkflowTemplateRecord(
            template_id=workflow_id,
            tenant_id=tenant_id,
            name=name,
            description=f"{name} description",
            status="draft",
            latest_version=1,
            created_at=created_at,
            updated_at=created_at,
        ),
        WorkflowTemplateVersionRecord(
            template_id=workflow_id,
            version=1,
            definition=_workflow_definition(),
            input_schema=_workflow_input_schema(),
            created_at=created_at,
        ),
    )


@pytest.mark.asyncio
async def test_workflow_routes_cover_lifecycle_and_template_compatibility(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind="finish",
                        summary="done",
                        final_output="triaged",
                    )
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        policy_response = await client.put(
            "/v1/tenants/tenant-a/policies",
            json={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
            },
        )
        assert policy_response.status_code == 200

        create_response = await client.post(
            "/v1/workflows",
            json={
                "workflow_id": "wf-triage",
                "tenant_id": "tenant-a",
                "name": "Incident Triage",
                "description": "Triage incidents with lifecycle routes",
                "definition": _workflow_definition(),
                "input_schema": _workflow_input_schema(),
                "created_by": "operator-a",
            },
        )

        assert create_response.status_code == 201
        assert create_response.json() == {
            "workflow_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triage incidents with lifecycle routes",
            "status": "draft",
            "latest_version": 1,
            "latest_published_version": None,
            "archived_at": None,
        }

        compatibility_list_response = await client.get(
            "/v1/workflow-templates",
            params={"tenant_id": "tenant-a"},
        )
        assert compatibility_list_response.status_code == 200
        assert compatibility_list_response.json() == [
            {
                "template_id": "wf-triage",
                "tenant_id": "tenant-a",
                "name": "Incident Triage",
                "description": "Triage incidents with lifecycle routes",
                "status": "draft",
                "latest_version": 1,
            }
        ]

        workflow_list_response = await client.get("/v1/workflows", params={"tenant_id": "tenant-a"})
        assert workflow_list_response.status_code == 200
        assert workflow_list_response.json() == {
            "items": [
                {
                    "workflow_id": "wf-triage",
                    "tenant_id": "tenant-a",
                    "name": "Incident Triage",
                    "status": "draft",
                    "latest_version": 1,
                }
            ],
            "next_cursor": None,
        }

        detail_response = await client.get(
            "/v1/workflows/wf-triage",
            params={"tenant_id": "tenant-a"},
        )
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload == {
            "workflow_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triage incidents with lifecycle routes",
            "status": "draft",
            "latest_version": 1,
            "latest_published_version": None,
            "created_at": detail_payload["created_at"],
            "updated_at": detail_payload["updated_at"],
            "archived_at": None,
            "latest_draft": {
                "version": 1,
                "definition": _workflow_definition(),
                "input_schema": _workflow_input_schema(),
                "source_version": None,
                "is_published": False,
                "created_by": "operator-a",
            },
            "latest_published": None,
            "version_summaries": [
                {
                    "version": 1,
                    "status": "draft",
                    "is_published": False,
                    "source_version": None,
                    "created_by": "operator-a",
                }
            ],
        }
        assert detail_payload["created_at"] is not None
        assert detail_payload["updated_at"] is not None

        create_version_response = await client.post(
            "/v1/workflows/wf-triage/versions",
            json={"tenant_id": "tenant-a", "created_by": "operator-b"},
        )
        assert create_version_response.status_code == 201
        assert create_version_response.json() == {
            "version": 2,
            "definition": _workflow_definition(),
            "input_schema": _workflow_input_schema(),
            "source_version": 1,
            "is_published": False,
            "created_by": "operator-b",
        }

        update_response = await client.put(
            "/v1/workflows/wf-triage/versions/2",
            json={
                "tenant_id": "tenant-a",
                "definition": {
                    **_workflow_definition(),
                    "runtime": {
                        "max_turns": 4,
                        "timeout_seconds": 300,
                        "tags": ["ops", "updated"],
                    },
                },
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                    "required": ["ticket_id", "severity"],
                },
            },
        )
        assert update_response.status_code == 200
        assert update_response.json() == {
            "version": 2,
            "definition": {
                **_workflow_definition(),
                "runtime": {
                    "max_turns": 4,
                    "timeout_seconds": 300,
                    "tags": ["ops", "updated"],
                },
            },
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "severity": {"type": "string"},
                },
                "required": ["ticket_id", "severity"],
            },
            "source_version": 1,
            "is_published": False,
            "created_by": "operator-b",
        }

        publish_response = await client.post(
            "/v1/workflows/wf-triage/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200
        assert publish_response.json() == {
            "workflow_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triage incidents with lifecycle routes",
            "status": "draft",
            "latest_version": 2,
            "latest_published_version": 1,
            "archived_at": None,
        }

        launch_response = await client.post(
            "/v1/workflows/wf-triage/launch",
            json={
                "tenant_id": "tenant-a",
                "version": 1,
                "input": {"ticket_id": "INC-42"},
                "metadata": {"requested_by": "operator-a"},
            },
        )
        assert launch_response.status_code == 201
        launch_payload = launch_response.json()
        assert launch_payload["tenant_id"] == "tenant-a"
        assert launch_payload["objective"] == "Triage incident INC-42"
        assert launch_payload["status"] == "created"
        assert launch_payload["result"] is None
        assert launch_payload["error"] is None
        assert launch_payload["workflow"] == {
            "workflow_id": "wf-triage",
            "version": 1,
            "name": "Incident Triage",
        }

        completed_payload = await _wait_for_run_status(client, launch_payload["run_id"], "completed")
        assert completed_payload["status"] == "completed"
        assert completed_payload["result"] == "triaged"

        template_launch_response = await client.post(
            "/v1/workflow-templates/wf-triage/launch",
            json={
                "tenant_id": "tenant-a",
                "version": 1,
                "input": {"ticket_id": "INC-43"},
                "metadata": {"requested_by": "operator-a"},
            },
        )
        assert template_launch_response.status_code == 201
        template_launch_payload = template_launch_response.json()
        assert template_launch_payload["tenant_id"] == launch_payload["tenant_id"]
        assert template_launch_payload["objective"] == "Triage incident INC-43"
        assert template_launch_payload["workflow_template"] == {
            "template_id": "wf-triage",
            "version": 1,
            "name": "Incident Triage",
        }

        delete_response = await client.delete(
            "/v1/workflows/wf-triage/versions/2",
            params={"tenant_id": "tenant-a"},
        )
        assert delete_response.status_code == 204
        assert delete_response.content == b""

        archive_response = await client.post(
            "/v1/workflows/wf-triage/archive",
            json={"tenant_id": "tenant-a"},
        )
        assert archive_response.status_code == 200
        archive_payload = archive_response.json()
        assert archive_payload["workflow_id"] == "wf-triage"
        assert archive_payload["tenant_id"] == "tenant-a"
        assert archive_payload["status"] == "archived"
        assert archive_payload["latest_version"] == 1
        assert archive_payload["latest_published_version"] == 1
        assert archive_payload["archived_at"] is not None

        archived_detail_response = await client.get(
            "/v1/workflows/wf-triage",
            params={"tenant_id": "tenant-a"},
        )
        assert archived_detail_response.status_code == 200
        archived_detail_payload = archived_detail_response.json()

        compatibility_detail_response = await client.get(
            "/v1/workflow-templates/wf-triage",
            params={"tenant_id": "tenant-a"},
        )
        assert compatibility_detail_response.status_code == 200
        compatibility_detail_payload = compatibility_detail_response.json()
        assert compatibility_detail_payload["template_id"] == archive_payload["workflow_id"]
        assert compatibility_detail_payload["tenant_id"] == archive_payload["tenant_id"]
        assert compatibility_detail_payload["status"] == archive_payload["status"]
        assert compatibility_detail_payload["latest_version"] == archive_payload["latest_version"]
        assert (
            compatibility_detail_payload["latest_published_version"]
            == archive_payload["latest_published_version"]
        )
        assert compatibility_detail_payload["created_at"] == archived_detail_payload["created_at"]
        assert compatibility_detail_payload["updated_at"] == archived_detail_payload["updated_at"]
        assert compatibility_detail_payload["archived_at"] == archive_payload["archived_at"]


@pytest.mark.asyncio
async def test_workflow_list_supports_lightweight_query_filters_and_pagination(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        newest_time = base_time + timedelta(minutes=1)

        await _seed_workflow(
            app,
            workflow_id="wf-alpha",
            tenant_id="tenant-a",
            name="Alpha Intake",
            created_at=base_time,
        )
        await _seed_workflow(
            app,
            workflow_id="wf-beta",
            tenant_id="tenant-a",
            name="Beta Intake",
            created_at=base_time,
        )
        await _seed_workflow(
            app,
            workflow_id="ops-gamma",
            tenant_id="tenant-a",
            name="Gamma Ops",
            created_at=newest_time,
        )
        await _seed_workflow(
            app,
            workflow_id="wf-tenant-b",
            tenant_id="tenant-b",
            name="Alpha Intake",
            created_at=newest_time,
        )

        list_response = await client.get("/v1/workflows", params={"tenant_id": "tenant-a"})
        assert list_response.status_code == 200
        assert list_response.json() == {
            "items": [
                {
                    "workflow_id": "ops-gamma",
                    "tenant_id": "tenant-a",
                    "name": "Gamma Ops",
                    "status": "draft",
                    "latest_version": 1,
                },
                {
                    "workflow_id": "wf-alpha",
                    "tenant_id": "tenant-a",
                    "name": "Alpha Intake",
                    "status": "draft",
                    "latest_version": 1,
                },
                {
                    "workflow_id": "wf-beta",
                    "tenant_id": "tenant-a",
                    "name": "Beta Intake",
                    "status": "draft",
                    "latest_version": 1,
                },
            ],
            "next_cursor": None,
        }

        filtered_response = await client.get(
            "/v1/workflows",
            params={
                "tenant_id": "tenant-a",
                "workflow_id_prefix": "wf-",
                "name_query": "ALPHA",
            },
        )
        assert filtered_response.status_code == 200
        assert filtered_response.json() == {
            "items": [
                {
                    "workflow_id": "wf-alpha",
                    "tenant_id": "tenant-a",
                    "name": "Alpha Intake",
                    "status": "draft",
                    "latest_version": 1,
                }
            ],
            "next_cursor": None,
        }

        first_page_response = await client.get(
            "/v1/workflows",
            params={"tenant_id": "tenant-a", "limit": 2},
        )
        assert first_page_response.status_code == 200
        first_page_payload = first_page_response.json()
        assert first_page_payload["items"] == [
            {
                "workflow_id": "ops-gamma",
                "tenant_id": "tenant-a",
                "name": "Gamma Ops",
                "status": "draft",
                "latest_version": 1,
            },
            {
                "workflow_id": "wf-alpha",
                "tenant_id": "tenant-a",
                "name": "Alpha Intake",
                "status": "draft",
                "latest_version": 1,
            },
        ]
        assert isinstance(first_page_payload["next_cursor"], str)

        second_page_response = await client.get(
            "/v1/workflows",
            params={
                "tenant_id": "tenant-a",
                "limit": 2,
                "cursor": first_page_payload["next_cursor"],
            },
        )
        assert second_page_response.status_code == 200
        assert second_page_response.json() == {
            "items": [
                {
                    "workflow_id": "wf-beta",
                    "tenant_id": "tenant-a",
                    "name": "Beta Intake",
                    "status": "draft",
                    "latest_version": 1,
                }
            ],
            "next_cursor": None,
        }

        invalid_cursor_response = await client.get(
            "/v1/workflows",
            params={"tenant_id": "tenant-a", "cursor": "not-a-valid-cursor"},
        )
        assert invalid_cursor_response.status_code == 400
        assert invalid_cursor_response.json() == {"detail": "invalid workflow list cursor"}

        invalid_limit_response = await client.get(
            "/v1/workflows",
            params={"tenant_id": "tenant-a", "limit": 0},
        )
        assert invalid_limit_response.status_code == 400
        assert invalid_limit_response.json() == {"detail": "limit must be between 1 and 100"}

        invalid_limit_type_response = await client.get(
            "/v1/workflows",
            params={"tenant_id": "tenant-a", "limit": "abc"},
        )
        assert invalid_limit_type_response.status_code == 400
        assert invalid_limit_type_response.json() == {"detail": "limit must be between 1 and 100"}

        missing_tenant_response = await client.get("/v1/workflows")
        assert missing_tenant_response.status_code == 400
        assert missing_tenant_response.json() == {"detail": "tenant_id is required"}

        tenant_b_response = await client.get("/v1/workflows", params={"tenant_id": "tenant-b"})
        assert tenant_b_response.status_code == 200
        assert tenant_b_response.json() == {
            "items": [
                {
                    "workflow_id": "wf-tenant-b",
                    "tenant_id": "tenant-b",
                    "name": "Alpha Intake",
                    "status": "draft",
                    "latest_version": 1,
                }
            ],
            "next_cursor": None,
        }
