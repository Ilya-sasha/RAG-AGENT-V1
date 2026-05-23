import importlib
import sqlite3

import pytest

from agent_runtime.domain.enums import AgentRole
from agent_runtime.domain.models import (
    AgentRecord,
    RunRecord,
    TenantPolicyRecord,
    WorkflowRunLinkRecord,
    WorkflowTemplateRecord,
    WorkflowTemplateVersionRecord,
)
from agent_runtime.models.base import DecisionKind, ModelDecision, ModelTurnInput
from agent_runtime.runtime.services import RunService
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


def load_workflow_service():
    return importlib.import_module("agent_runtime.workflows.service")


def load_workflow_repository():
    module = importlib.import_module("agent_runtime.workflows.repository")
    return module.WorkflowRepository


def test_validate_template_definition_rejects_unsupported_worker_role() -> None:
    definition = {
        "entrypoint": {
            "objective_template": "Process {ticket_id}",
            "result_contract": "string",
        },
        "agents": {
            "allowed_worker_roles": ["researcher", "manager"],
            "max_worker_count": 2,
        },
        "tools": {
            "allowed_tools": ["rag_search"],
            "approval_required_tools": [],
        },
        "knowledge": {
            "default_kb_ids": ["kb-a"],
            "allow_kb_override": False,
        },
        "runtime": {
            "max_turns": 6,
            "timeout_seconds": 300,
            "tags": ["triage"],
        },
        "launch_policy": {
            "allow_input_objective_override": False,
            "require_published_version": True,
        },
    }

    errors = load_workflow_service().validate_template_definition(definition)

    assert errors == ["unsupported worker role: manager"]


def test_validate_template_definition_rejects_negative_limits_and_duplicate_identifiers() -> None:
    definition = {
        "entrypoint": {
            "objective_template": "Process {ticket_id}",
            "result_contract": "string",
        },
        "agents": {
            "allowed_worker_roles": ["researcher"],
            "max_worker_count": -1,
        },
        "tools": {
            "allowed_tools": ["rag_search", "rag_search"],
            "approval_required_tools": [],
        },
        "knowledge": {
            "default_kb_ids": ["kb-a", "kb-a"],
            "allow_kb_override": False,
        },
        "runtime": {
            "max_turns": -2,
            "timeout_seconds": -5,
            "tags": ["triage"],
        },
        "launch_policy": {
            "allow_input_objective_override": False,
            "require_published_version": True,
        },
    }

    errors = load_workflow_service().validate_template_definition(definition)

    assert errors == [
        "agents.max_worker_count must be non-negative",
        "runtime.max_turns must be non-negative",
        "runtime.timeout_seconds must be non-negative",
        "tools.allowed_tools contains duplicate entries: rag_search",
        "knowledge.default_kb_ids contains duplicate entries: kb-a",
    ]


def test_validate_template_definition_rejects_invalid_input_schema_envelope() -> None:
    service = load_workflow_service()
    with pytest.raises(service.WorkflowTemplateValidationError, match="input_schema must declare type=object"):
        service.WorkflowService._validate_workflow_input_schema({"type": "array"})


def test_assemble_template_launch_renders_objective_and_effective_policy() -> None:
    assembled = load_workflow_service().assemble_template_launch(
        tenant_id="tenant-a",
        template_id="wf-triage",
        template_name="Incident Triage",
        version=2,
        definition={
            "entrypoint": {
                "objective_template": "Triage incident {ticket_id}",
                "result_contract": "string",
            },
            "agents": {
                "allowed_worker_roles": ["researcher"],
                "max_worker_count": 1,
            },
            "tools": {
                "allowed_tools": ["rag_search", "payment-api"],
                "approval_required_tools": ["payment-api"],
            },
            "knowledge": {
                "default_kb_ids": ["kb-ops"],
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
        },
        launch_input={"ticket_id": "INC-42"},
        tenant_allowed_tools=["rag_search", "payment-api", "email-api"],
        tenant_approval_required_tools=["email-api"],
        existing_kb_ids=["kb-ops"],
    )

    assert assembled.objective == "Triage incident INC-42"
    assert assembled.default_kb_ids == ["kb-ops"]
    assert set(assembled.effective_allowed_tools) == {"payment-api", "rag_search"}
    assert set(assembled.effective_approval_required_tools) == {"email-api", "payment-api"}


def test_assemble_template_launch_rejects_missing_knowledge_base() -> None:
    with pytest.raises(ValueError, match="unknown knowledge base: kb-missing"):
        load_workflow_service().assemble_template_launch(
            tenant_id="tenant-a",
            template_id="wf-triage",
            template_name="Incident Triage",
            version=1,
            definition={
                "entrypoint": {
                    "objective_template": "Triage {ticket_id}",
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
                    "default_kb_ids": ["kb-missing"],
                    "allow_kb_override": False,
                },
                "runtime": {
                    "max_turns": 4,
                    "timeout_seconds": 60,
                    "tags": [],
                },
                "launch_policy": {
                    "allow_input_objective_override": False,
                    "require_published_version": True,
                },
            },
            launch_input={"ticket_id": "INC-1"},
            tenant_allowed_tools=["rag_search"],
            tenant_approval_required_tools=[],
            existing_kb_ids=["kb-ops"],
        )


@pytest.mark.asyncio
async def test_workflow_repository_round_trip_and_publish_version(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)

        template = WorkflowTemplateRecord(
            template_id="wf-triage",
            tenant_id="tenant-a",
            name="Incident Triage",
            description="Triage incident workflows",
            status="draft",
            latest_version=1,
        )
        initial_version = WorkflowTemplateVersionRecord(
            template_id="wf-triage",
            version=1,
            definition={
                "entrypoint": {"objective_template": "Triage {ticket_id}"},
                "tools": {"allowed_tools": ["rag_search"]},
            },
            input_schema={"type": "object"},
            created_by="operator-a",
        )

        await workflow_repository.create_template(template, initial_version)
        await workflow_repository.publish_version("tenant-a", "wf-triage", 1)
        await runtime_repository.create_run(
            RunRecord(
                run_id="run-1",
                tenant_id="tenant-a",
                objective="Triage INC-42",
            ),
            AgentRecord(
                agent_id="agent-1",
                run_id="run-1",
                role=AgentRole.SUPERVISOR,
                objective="Triage INC-42",
            ),
        )
        await workflow_repository.create_run_link(
            WorkflowRunLinkRecord(
                run_id="run-1",
                tenant_id="tenant-a",
                template_id="wf-triage",
                template_version=1,
                template_name="Incident Triage",
                launch_input={"ticket_id": "INC-42"},
                launch_metadata={"requested_by": "operator-a"},
                effective_workflow_policy={"allowed_tools": ["rag_search"]},
            )
        )

        stored_template = await workflow_repository.get_template("tenant-a", "wf-triage")
        stored_version = await workflow_repository.get_template_version("tenant-a", "wf-triage", 1)
        latest_published = await workflow_repository.get_latest_published_version("tenant-a", "wf-triage")
        listed_templates = await workflow_repository.list_templates("tenant-a")
        stored_run_link = await workflow_repository.get_run_link("run-1")

        assert stored_template is not None
        assert stored_template.status == "published"
        assert stored_template.latest_version == 1
        assert stored_version is not None
        assert stored_version.is_published is True
        assert stored_version.published_at is not None
        assert latest_published is not None
        assert latest_published.version == 1
        assert [item.template_id for item in listed_templates] == ["wf-triage"]
        assert stored_run_link is not None
        assert stored_run_link.template_version == 1
        assert stored_run_link.launch_input == {"ticket_id": "INC-42"}
        assert stored_run_link.launch_metadata == {"requested_by": "operator-a"}
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_create_draft_version_copies_latest_and_rejects_second_draft(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incidents",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object", "required": ["ticket_id"]},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        draft = await service.create_template_version_draft(
            tenant_id="tenant-a",
            template_id="wf-triage",
            created_by="operator-b",
        )

        assert draft.version == 2
        assert draft.source_version == 1
        assert draft.definition == {"entrypoint": {"objective_template": "Triage {ticket_id}"}}

        with pytest.raises(workflow_service_module.WorkflowTemplateConflictError, match="draft already exists"):
            await service.create_template_version_draft(
                tenant_id="tenant-a",
                template_id="wf-triage",
                created_by="operator-c",
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_publish_template_version_aggregates_preflight_errors(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        runtime_repository = RuntimeRepository(session_factory)
        await runtime_repository.upsert_tenant_policy(
            TenantPolicyRecord(
                tenant_id="tenant-a",
                allowed_tools=["rag_search"],
                approval_required_tools=[],
            )
        )

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-bad",
                tenant_id="tenant-a",
                name="Broken Workflow",
                description="Broken workflow",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-bad",
                version=1,
                definition={
                    "entrypoint": {"objective_template": ""},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": -1},
                    "tools": {"allowed_tools": ["payment-api"], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": ["kb-missing"], "allow_kb_override": False},
                    "runtime": {"max_turns": -2, "timeout_seconds": 60, "tags": []},
                    "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
                },
                input_schema={"type": "array"},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplatePreflightError) as exc_info:
            await service.publish_template_version(
                tenant_id="tenant-a",
                template_id="wf-bad",
                version=1,
            )

        assert exc_info.value.errors == [
            "entrypoint.objective_template must be a non-empty string",
            "agents.max_worker_count must be non-negative",
            "runtime.max_turns must be non-negative",
            "input_schema must declare type=object",
            "template tools exceed tenant policy: payment-api",
            "unknown knowledge base: kb-missing",
        ]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_publish_template_version_rejects_already_published_version_via_preflight(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        runtime_repository = RuntimeRepository(session_factory)
        await runtime_repository.upsert_tenant_policy(
            TenantPolicyRecord(
                tenant_id="tenant-a",
                allowed_tools=["rag_search"],
                approval_required_tools=[],
            )
        )

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-published",
                tenant_id="tenant-a",
                name="Published Workflow",
                description="Published workflow",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-published",
                version=1,
                definition={
                    "entrypoint": {"objective_template": "Triage {ticket_id}"},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                    "tools": {"allowed_tools": ["rag_search"], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                    "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": []},
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                input_schema={"type": "object", "required": ["ticket_id"]},
                created_by="operator-a",
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-published", 1)

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplatePreflightError) as exc_info:
            await service.publish_template_version(
                tenant_id="tenant-a",
                template_id="wf-published",
                version=1,
            )

        assert exc_info.value.errors == [
            "workflow template version is not eligible for publish: wf-published:1"
        ]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_publish_template_version_aggregates_missing_tenant_policy(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        runtime_repository = RuntimeRepository(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-no-policy",
                tenant_id="tenant-a",
                name="No Policy Workflow",
                description="Missing tenant policy",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-no-policy",
                version=1,
                definition={
                    "entrypoint": {"objective_template": "Triage {ticket_id}"},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                    "tools": {"allowed_tools": [], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                    "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": []},
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                input_schema={"type": "object", "required": ["ticket_id"]},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplatePreflightError) as exc_info:
            await service.publish_template_version(
                tenant_id="tenant-a",
                template_id="wf-no-policy",
                version=1,
            )

        assert exc_info.value.errors == ["tenant policy not found: tenant-a"]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_publish_template_version_deduplicates_tool_and_kb_identifiers_in_preflight(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        runtime_repository = RuntimeRepository(session_factory)
        await runtime_repository.upsert_tenant_policy(
            TenantPolicyRecord(
                tenant_id="tenant-a",
                allowed_tools=["rag_search"],
                approval_required_tools=[],
            )
        )

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-duplicates",
                tenant_id="tenant-a",
                name="Duplicate Identifiers Workflow",
                description="Deduplicate preflight message identifiers",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-duplicates",
                version=1,
                definition={
                    "entrypoint": {"objective_template": "Triage {ticket_id}"},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                    "tools": {
                        "allowed_tools": ["payment-api", "payment-api", "slack-api", "slack-api"],
                        "approval_required_tools": [],
                    },
                    "knowledge": {
                        "default_kb_ids": ["kb-missing", "kb-missing", "kb-other", "kb-other"],
                        "allow_kb_override": False,
                    },
                    "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": []},
                    "launch_policy": {
                        "allow_input_objective_override": False,
                        "require_published_version": True,
                    },
                },
                input_schema={"type": "object", "required": ["ticket_id"]},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplatePreflightError) as exc_info:
            await service.publish_template_version(
                tenant_id="tenant-a",
                template_id="wf-duplicates",
                version=1,
            )

        assert "template tools exceed tenant policy: payment-api, slack-api" in exc_info.value.errors
        assert "unknown knowledge base: kb-missing, kb-other" in exc_info.value.errors
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_get_template_detail_returns_latest_draft_and_latest_published(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incidents",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object", "required": ["ticket_id"]},
                created_by="operator-a",
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-triage", 1)
        await workflow_repository.create_copied_draft_version(
            "tenant-a",
            "wf-triage",
            created_by="operator-b",
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        detail = await service.get_template_detail("tenant-a", "wf-triage")

        assert detail["template"].template_id == "wf-triage"
        assert detail["template"].latest_version == 2
        assert detail["template"].latest_published_version == 1
        assert detail["latest_draft"] is not None
        assert detail["latest_draft"].version == 2
        assert detail["latest_published"] is not None
        assert detail["latest_published"].version == 1
        assert detail["version_summaries"] == [
            {
                "version": 2,
                "status": "draft",
                "is_published": False,
                "source_version": 1,
                "created_by": "operator-b",
            },
            {
                "version": 1,
                "status": "published",
                "is_published": True,
                "source_version": None,
                "created_by": "operator-a",
            },
        ]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_archive_template_rejects_unpublished_only_workflow(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-draft",
                tenant_id="tenant-a",
                name="Draft Only Workflow",
                description="Never published",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-draft",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(
            workflow_service_module.WorkflowTemplateValidationError,
            match="cannot archive unpublished workflow template: wf-draft",
        ):
            await service.archive_template("tenant-a", "wf-draft")
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_replace_template_version_draft_updates_definition_and_input_schema(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-edit",
                tenant_id="tenant-a",
                name="Editable Workflow",
                description="Draft replacement",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-edit",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-edit", 1)
        draft = await workflow_repository.create_copied_draft_version(
            "tenant-a",
            "wf-edit",
            created_by="operator-b",
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        replaced = await service.replace_template_version_draft(
            tenant_id="tenant-a",
            template_id="wf-edit",
            version=draft.version,
            definition={
                "entrypoint": {"objective_template": "Escalate {ticket_id}"},
                "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                "tools": {"allowed_tools": [], "approval_required_tools": []},
                "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": []},
                "launch_policy": {
                    "allow_input_objective_override": False,
                    "require_published_version": True,
                },
            },
            input_schema={"type": "object", "required": ["ticket_id"]},
        )

        assert replaced.version == 2
        assert replaced.definition["entrypoint"]["objective_template"] == "Escalate {ticket_id}"
        assert replaced.input_schema == {"type": "object", "required": ["ticket_id"]}
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_delete_template_version_removes_draft_and_rewinds_header(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-delete",
                tenant_id="tenant-a",
                name="Delete Draft Workflow",
                description="Draft deletion",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-delete",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-delete", 1)
        draft = await workflow_repository.create_copied_draft_version(
            "tenant-a",
            "wf-delete",
            created_by="operator-b",
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        await service.delete_template_version(
            tenant_id="tenant-a",
            template_id="wf-delete",
            version=draft.version,
        )

        detail = await service.get_template_detail("tenant-a", "wf-delete")

        assert detail["template"].latest_version == 1
        assert detail["template"].latest_published_version == 1
        assert detail["template"].status == "published"
        assert detail["latest_draft"] is None
        assert detail["latest_published"] is not None
        assert detail["latest_published"].version == 1
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_list_workflow_summaries_filters_and_paginates(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-gamma",
                tenant_id="tenant-a",
                name="Gamma Workflow",
                description="third",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-gamma",
                version=1,
                definition={"entrypoint": {"objective_template": "Gamma"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-beta",
                tenant_id="tenant-a",
                name="Beta Workflow",
                description="second",
                status="published",
                latest_version=2,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-beta",
                version=2,
                definition={"entrypoint": {"objective_template": "Beta"}},
                input_schema={"type": "object"},
                is_published=True,
                created_by="operator-b",
            ),
        )
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="ops-alpha",
                tenant_id="tenant-a",
                name="Alpha Incident Flow",
                description="first",
                status="archived",
                latest_version=3,
            ),
            WorkflowTemplateVersionRecord(
                template_id="ops-alpha",
                version=3,
                definition={"entrypoint": {"objective_template": "Alpha"}},
                input_schema={"type": "object"},
                is_published=True,
                created_by="operator-c",
            ),
        )

        first_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-",
            name_query="workflow",
            limit=1,
            cursor=None,
        )

        assert [item["workflow_id"] for item in first_page["items"]] == ["wf-beta"]
        assert first_page["next_cursor"] is not None

        second_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-",
            name_query="workflow",
            limit=1,
            cursor=first_page["next_cursor"],
        )

        assert [item["workflow_id"] for item in second_page["items"]] == ["wf-gamma"]
        assert second_page["next_cursor"] is None

        exact_match_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-beta",
            name_query=None,
            limit=10,
            cursor=None,
        )

        assert [item["workflow_id"] for item in exact_match_page["items"]] == ["wf-beta"]
        assert exact_match_page["next_cursor"] is None
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_list_workflow_summaries_is_tenant_scoped_and_rejects_bad_cursor(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-tenant-a",
                tenant_id="tenant-a",
                name="Tenant A Flow",
                description="a",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-tenant-a",
                version=1,
                definition={"entrypoint": {"objective_template": "A"}},
                input_schema={"type": "object"},
            ),
        )
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-tenant-b",
                tenant_id="tenant-b",
                name="Tenant B Flow",
                description="b",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-tenant-b",
                version=1,
                definition={"entrypoint": {"objective_template": "B"}},
                input_schema={"type": "object"},
            ),
        )

        tenant_a_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix=None,
            name_query=None,
            limit=10,
            cursor=None,
        )

        assert [item["workflow_id"] for item in tenant_a_page["items"]] == ["wf-tenant-a"]

        with pytest.raises(ValueError, match="invalid workflow list cursor"):
            await workflow_repository.list_workflow_summaries(
                tenant_id="tenant-a",
                workflow_id_prefix=None,
                name_query=None,
                limit=10,
                cursor="not-a-valid-cursor",
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_list_workflows_validates_limit_and_returns_items_plus_next_cursor(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-summary",
                tenant_id="tenant-a",
                name="Summary Workflow",
                description="summary",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-summary",
                version=1,
                definition={"entrypoint": {"objective_template": "Summary"}},
                input_schema={"type": "object"},
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(
            workflow_service_module.WorkflowTemplateValidationError,
            match="limit must be between 1 and 100",
        ):
            await service.list_workflows(
                tenant_id="tenant-a",
                workflow_id_prefix=None,
                name_query=None,
                limit=0,
                cursor=None,
            )

        with pytest.raises(
            workflow_service_module.WorkflowTemplateValidationError,
            match="limit must be between 1 and 100",
        ):
            await service.list_workflows(
                tenant_id="tenant-a",
                workflow_id_prefix=None,
                name_query=None,
                limit=101,
                cursor=None,
            )

        for invalid_limit in ("10", True, False):
            with pytest.raises(
                workflow_service_module.WorkflowTemplateValidationError,
                match="limit must be between 1 and 100",
            ):
                await service.list_workflows(
                    tenant_id="tenant-a",
                    workflow_id_prefix=None,
                    name_query=None,
                    limit=invalid_limit,
                    cursor=None,
                )

        with pytest.raises(
            workflow_service_module.WorkflowTemplateValidationError,
            match="invalid workflow list cursor",
        ):
            await service.list_workflows(
                tenant_id="tenant-a",
                workflow_id_prefix=None,
                name_query=None,
                limit=10,
                cursor="not-a-valid-cursor",
            )

        result = await service.list_workflows(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-",
            name_query="summary",
            limit=10,
            cursor=None,
        )

        assert [item["workflow_id"] for item in result["items"]] == ["wf-summary"]
        assert result["next_cursor"] is None
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_create_template_version_keeps_existing_version_immutable(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        template = WorkflowTemplateRecord(
            template_id="wf-triage",
            tenant_id="tenant-a",
            name="Incident Triage",
            description="Triage incident workflows",
            status="draft",
            latest_version=1,
        )
        version_one = WorkflowTemplateVersionRecord(
            template_id="wf-triage",
            version=1,
            definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
            input_schema={"type": "object"},
            created_by="operator-a",
        )
        version_two = WorkflowTemplateVersionRecord(
            template_id="wf-triage",
            version=2,
            definition={"entrypoint": {"objective_template": "Escalate {ticket_id}"}},
            input_schema={"type": "object", "required": ["ticket_id"]},
            created_by="operator-b",
        )

        await workflow_repository.create_template(template, version_one)
        await workflow_repository.create_template_version("tenant-a", "wf-triage", version_two)

        stored_template = await workflow_repository.get_template("tenant-a", "wf-triage")
        stored_version_one = await workflow_repository.get_template_version("tenant-a", "wf-triage", 1)
        stored_version_two = await workflow_repository.get_template_version("tenant-a", "wf-triage", 2)

        assert stored_template is not None
        assert stored_template.latest_version == 2
        assert stored_version_one is not None
        assert stored_version_one.definition == {
            "entrypoint": {"objective_template": "Triage {ticket_id}"}
        }
        assert stored_version_one.input_schema == {"type": "object"}
        assert stored_version_two is not None
        assert stored_version_two.definition == {
            "entrypoint": {"objective_template": "Escalate {ticket_id}"}
        }
        assert stored_version_two.input_schema == {"type": "object", "required": ["ticket_id"]}
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_publish_older_version_does_not_regress_latest_version(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        template = WorkflowTemplateRecord(
            template_id="wf-triage",
            tenant_id="tenant-a",
            name="Incident Triage",
            description="Triage incident workflows",
            status="draft",
            latest_version=1,
        )
        version_one = WorkflowTemplateVersionRecord(
            template_id="wf-triage",
            version=1,
            definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
            input_schema={"type": "object"},
            created_by="operator-a",
        )
        version_two = WorkflowTemplateVersionRecord(
            template_id="wf-triage",
            version=2,
            definition={"entrypoint": {"objective_template": "Escalate {ticket_id}"}},
            input_schema={"type": "object", "required": ["ticket_id"]},
            created_by="operator-b",
        )

        await workflow_repository.create_template(template, version_one)
        await workflow_repository.create_template_version("tenant-a", "wf-triage", version_two)
        await workflow_repository.publish_version("tenant-a", "wf-triage", 1)

        stored_template = await workflow_repository.get_template("tenant-a", "wf-triage")
        stored_version_one = await workflow_repository.get_template_version("tenant-a", "wf-triage", 1)
        stored_version_two = await workflow_repository.get_template_version("tenant-a", "wf-triage", 2)
        latest_published = await workflow_repository.get_latest_published_version("tenant-a", "wf-triage")

        assert stored_template is not None
        assert stored_template.status == "draft"
        assert stored_template.latest_version == 2
        assert stored_template.latest_published_version == 1
        assert stored_version_one is not None
        assert stored_version_one.is_published is True
        assert stored_version_one.published_at is not None
        assert stored_version_two is not None
        assert stored_version_two.is_published is False
        assert latest_published is not None
        assert latest_published.version == 1
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_republish_older_version_does_not_regress_latest_published_version_or_header(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-history",
                tenant_id="tenant-a",
                name="Workflow History",
                description="Published history should not regress",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-history",
                version=1,
                definition={"entrypoint": {"objective_template": "v1"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await workflow_repository.create_template_version(
            "tenant-a",
            "wf-history",
            WorkflowTemplateVersionRecord(
                template_id="wf-history",
                version=2,
                definition={"entrypoint": {"objective_template": "v2"}},
                input_schema={"type": "object"},
                created_by="operator-b",
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-history", 2)
        await workflow_repository.publish_version("tenant-a", "wf-history", 1)

        stored_template = await workflow_repository.get_template("tenant-a", "wf-history")

        assert stored_template is not None
        assert stored_template.latest_published_version == 2
        assert stored_template.status == "published"
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_delete_draft_version_keeps_published_history_and_rewinds_latest_version(
    tmp_path,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incident workflows",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-triage", 1)

        copied_draft = await workflow_repository.create_copied_draft_version(
            "tenant-a",
            "wf-triage",
            created_by="operator-b",
        )
        assert copied_draft.version == 2
        assert copied_draft.source_version == 1

        await workflow_repository.delete_draft_version("tenant-a", "wf-triage", 2)

        stored_template = await workflow_repository.get_template("tenant-a", "wf-triage")
        stored_draft = await workflow_repository.get_draft_version("tenant-a", "wf-triage")
        stored_version_one = await workflow_repository.get_template_version("tenant-a", "wf-triage", 1)
        latest_published = await workflow_repository.get_latest_published_version("tenant-a", "wf-triage")

        assert stored_template is not None
        assert stored_template.latest_version == 1
        assert stored_template.latest_published_version == 1
        assert stored_template.status == "published"
        assert stored_draft is None
        assert stored_version_one is not None
        assert stored_version_one.is_published is True
        assert latest_published is not None
        assert latest_published.version == 1
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_delete_draft_version_rejects_deleting_last_remaining_version(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-last-draft",
                tenant_id="tenant-a",
                name="Last Draft Workflow",
                description="Protect final version",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-last-draft",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )

        with pytest.raises(ValueError, match="cannot delete last remaining draft version"):
            await workflow_repository.delete_draft_version("tenant-a", "wf-last-draft", 1)
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_replace_draft_version_updates_definition_and_input_schema(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-edit",
                tenant_id="tenant-a",
                name="Editable Workflow",
                description="Draft replacement",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-edit",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )

        draft = await workflow_repository.create_copied_draft_version(
            "tenant-a",
            "wf-edit",
            created_by="operator-b",
        )
        replaced = await workflow_repository.replace_draft_version(
            "tenant-a",
            "wf-edit",
            draft.version,
            definition={"entrypoint": {"objective_template": "Escalate {ticket_id}"}},
            input_schema={"type": "object", "required": ["ticket_id"]},
        )
        stored_draft = await workflow_repository.get_template_version("tenant-a", "wf-edit", draft.version)

        assert replaced.definition == {"entrypoint": {"objective_template": "Escalate {ticket_id}"}}
        assert replaced.input_schema == {"type": "object", "required": ["ticket_id"]}
        assert stored_draft is not None
        assert stored_draft.definition == {"entrypoint": {"objective_template": "Escalate {ticket_id}"}}
        assert stored_draft.input_schema == {"type": "object", "required": ["ticket_id"]}
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_repository_create_copied_draft_version_rejects_second_draft(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-draft",
                tenant_id="tenant-a",
                name="Draft Workflow",
                description="Draft duplication guard",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-draft",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )

        first_draft = await workflow_repository.create_copied_draft_version(
            "tenant-a",
            "wf-draft",
            created_by="operator-b",
        )

        with pytest.raises(ValueError, match="draft already exists"):
            await workflow_repository.create_copied_draft_version(
                "tenant-a",
                "wf-draft",
                created_by="operator-c",
            )

        stored_template = await workflow_repository.get_template("tenant-a", "wf-draft")
        listed_versions = await workflow_repository.list_template_versions("tenant-a", "wf-draft")

        assert first_draft.version == 2
        assert stored_template is not None
        assert stored_template.latest_version == 2
        assert [
            {
                "version": item["version"],
                "status": item["status"],
                "is_published": item["is_published"],
                "source_version": item["source_version"],
                "created_by": item["created_by"],
            }
            for item in listed_versions
        ] == [
            {
                "version": 2,
                "status": "draft",
                "is_published": False,
                "source_version": 1,
                "created_by": "operator-b",
            },
            {
                "version": 1,
                "status": "draft",
                "is_published": False,
                "source_version": None,
                "created_by": "operator-a",
            },
        ]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_init_db_upgrades_existing_workflow_tables_for_v2_lifecycle_columns(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE workflow_templates (
                template_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT uq_workflow_templates_tenant_template UNIQUE (tenant_id, template_id)
            );
            CREATE TABLE workflow_template_versions (
                version_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                definition JSON NOT NULL,
                input_schema JSON NOT NULL,
                is_published BOOLEAN NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT,
                CONSTRAINT fk_workflow_template_versions_template FOREIGN KEY (tenant_id, template_id)
                    REFERENCES workflow_templates (tenant_id, template_id),
                CONSTRAINT uq_workflow_template_versions UNIQUE (tenant_id, template_id, version)
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    db_url = f"sqlite+aiosqlite:///{db_path}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-upgrade",
                tenant_id="tenant-a",
                name="Upgraded Workflow",
                description="Lifecycle upgrade path",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-upgrade",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
                source_version=7,
            ),
        )
        await workflow_repository.publish_version("tenant-a", "wf-upgrade", 1)
        archived_template = await workflow_repository.archive_template("tenant-a", "wf-upgrade")

        stored_template = await workflow_repository.get_template("tenant-a", "wf-upgrade")
        stored_version = await workflow_repository.get_template_version("tenant-a", "wf-upgrade", 1)

        assert archived_template.archived_at is not None
        assert stored_template is not None
        assert stored_template.latest_published_version == 1
        assert stored_template.archived_at is not None
        assert stored_version is not None
        assert stored_version.source_version == 7
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_init_db_backfills_latest_published_version_for_existing_published_workflows(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE workflow_templates (
                template_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT uq_workflow_templates_tenant_template UNIQUE (tenant_id, template_id)
            );
            CREATE TABLE workflow_template_versions (
                version_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                definition JSON NOT NULL,
                input_schema JSON NOT NULL,
                is_published BOOLEAN NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT,
                CONSTRAINT fk_workflow_template_versions_template FOREIGN KEY (tenant_id, template_id)
                    REFERENCES workflow_templates (tenant_id, template_id),
                CONSTRAINT uq_workflow_template_versions UNIQUE (tenant_id, template_id, version)
            );
            INSERT INTO workflow_templates (
                template_id, tenant_id, name, description, status, latest_version, created_at, updated_at
            ) VALUES (
                'wf-legacy', 'tenant-a', 'Legacy Workflow', 'Published before upgrade', 'published', 3,
                '2026-05-18T00:00:00Z', '2026-05-18T00:00:00Z'
            );
            INSERT INTO workflow_template_versions (
                tenant_id, template_id, version, definition, input_schema, is_published, published_at, created_at, created_by
            ) VALUES
            (
                'tenant-a', 'wf-legacy', 1, '{"entrypoint":{"objective_template":"v1"}}', '{"type":"object"}',
                1, '2026-05-18T00:00:00Z', '2026-05-18T00:00:00Z', 'operator-a'
            ),
            (
                'tenant-a', 'wf-legacy', 2, '{"entrypoint":{"objective_template":"v2"}}', '{"type":"object"}',
                1, '2026-05-18T01:00:00Z', '2026-05-18T01:00:00Z', 'operator-b'
            ),
            (
                'tenant-a', 'wf-legacy', 3, '{"entrypoint":{"objective_template":"v3"}}', '{"type":"object"}',
                0, NULL, '2026-05-18T02:00:00Z', 'operator-c'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    db_url = f"sqlite+aiosqlite:///{db_path}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        stored_template = await workflow_repository.get_template("tenant-a", "wf-legacy")

        assert stored_template is not None
        assert stored_template.latest_published_version == 2
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_init_db_backfills_latest_published_version_for_draft_headers_with_published_history(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE workflow_templates (
                template_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT uq_workflow_templates_tenant_template UNIQUE (tenant_id, template_id)
            );
            CREATE TABLE workflow_template_versions (
                version_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                definition JSON NOT NULL,
                input_schema JSON NOT NULL,
                is_published BOOLEAN NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT,
                CONSTRAINT fk_workflow_template_versions_template FOREIGN KEY (tenant_id, template_id)
                    REFERENCES workflow_templates (tenant_id, template_id),
                CONSTRAINT uq_workflow_template_versions UNIQUE (tenant_id, template_id, version)
            );
            INSERT INTO workflow_templates (
                template_id, tenant_id, name, description, status, latest_version, created_at, updated_at
            ) VALUES (
                'wf-legacy-draft', 'tenant-a', 'Legacy Draft Workflow', 'Draft with published history', 'draft', 3,
                '2026-05-18T00:00:00Z', '2026-05-18T00:00:00Z'
            );
            INSERT INTO workflow_template_versions (
                tenant_id, template_id, version, definition, input_schema, is_published, published_at, created_at, created_by
            ) VALUES
            (
                'tenant-a', 'wf-legacy-draft', 1, '{"entrypoint":{"objective_template":"v1"}}', '{"type":"object"}',
                1, '2026-05-18T00:00:00Z', '2026-05-18T00:00:00Z', 'operator-a'
            ),
            (
                'tenant-a', 'wf-legacy-draft', 2, '{"entrypoint":{"objective_template":"v2"}}', '{"type":"object"}',
                1, '2026-05-18T01:00:00Z', '2026-05-18T01:00:00Z', 'operator-b'
            ),
            (
                'tenant-a', 'wf-legacy-draft', 3, '{"entrypoint":{"objective_template":"v3"}}', '{"type":"object"}',
                0, NULL, '2026-05-18T02:00:00Z', 'operator-c'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    db_url = f"sqlite+aiosqlite:///{db_path}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        workflow_repository = load_workflow_repository()(session_factory)
        stored_template = await workflow_repository.get_template("tenant-a", "wf-legacy-draft")

        assert stored_template is not None
        assert stored_template.latest_published_version == 2
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_init_db_upgrades_existing_workflow_run_links_with_launch_metadata(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                result JSON,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE workflow_templates (
                template_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT uq_workflow_templates_tenant_template UNIQUE (tenant_id, template_id)
            );
            CREATE TABLE workflow_run_links (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                template_version INTEGER NOT NULL,
                template_name TEXT NOT NULL,
                launch_input JSON NOT NULL,
                effective_workflow_policy JSON NOT NULL,
                created_at TEXT NOT NULL,
                CONSTRAINT fk_workflow_run_links_template FOREIGN KEY (tenant_id, template_id)
                    REFERENCES workflow_templates (tenant_id, template_id),
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    db_url = f"sqlite+aiosqlite:///{db_path}"
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
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await runtime_repository.create_run(
            RunRecord(
                run_id="run-1",
                tenant_id="tenant-a",
                objective="Triage INC-42",
            ),
            AgentRecord(
                agent_id="agent-1",
                run_id="run-1",
                role=AgentRole.SUPERVISOR,
                objective="Triage INC-42",
            ),
        )

        await workflow_repository.create_run_link(
            WorkflowRunLinkRecord(
                run_id="run-1",
                tenant_id="tenant-a",
                template_id="wf-triage",
                template_version=1,
                template_name="Incident Triage",
                launch_input={"ticket_id": "INC-42"},
                launch_metadata={"requested_by": "operator-a"},
                effective_workflow_policy={"allowed_tools": ["rag_search"]},
            )
        )

        stored_run_link = await workflow_repository.get_run_link("run-1")

        assert stored_run_link is not None
        assert stored_run_link.launch_metadata == {"requested_by": "operator-a"}
    finally:
        await dispose_session_factory(session_factory)


class ImmediateFinishModelClient:
    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        del turn
        return ModelDecision(
            kind=DecisionKind.FINISH,
            summary="done",
            final_output="completed",
        )


class FailingWorkflowRepository:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    async def create_run_link(self, link: WorkflowRunLinkRecord) -> None:
        self.run_ids.append(link.run_id)
        raise RuntimeError("persist link failed")


@pytest.mark.asyncio
async def test_run_service_create_run_from_template_launch_persists_run_link(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    run_service: RunService | None = None
    try:
        await init_db(session_factory)

        runtime_repository = RuntimeRepository(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        event_hub = EventStreamHub(runtime_repository.list_events)
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
        run_service = RunService(
            runtime_repository,
            ImmediateFinishModelClient(),
            event_hub,
            workflow_repository=workflow_repository,
        )

        run = await run_service.create_run_from_template_launch(
            tenant_id="tenant-a",
            objective="Triage incident INC-42",
            template_id="wf-triage",
            template_version=2,
            template_name="Incident Triage",
            launch_input={"ticket_id": "INC-42"},
            launch_metadata={"requested_by": "operator-a"},
            effective_workflow_policy={
                "allowed_tools": ["rag_search"],
                "approval_required_tools": [],
                "default_kb_ids": ["kb-ops"],
            },
        )

        stored_run = await runtime_repository.get_run(run.run_id)
        stored_run_link = await workflow_repository.get_run_link(run.run_id)

        assert stored_run is not None
        assert stored_run.objective == "Triage incident INC-42"
        assert stored_run_link is not None
        assert stored_run_link.template_id == "wf-triage"
        assert stored_run_link.template_version == 2
        assert stored_run_link.template_name == "Incident Triage"
        assert stored_run_link.launch_input == {"ticket_id": "INC-42"}
        assert stored_run_link.launch_metadata == {"requested_by": "operator-a"}
    finally:
        if run_service is not None:
            await run_service.shutdown()
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_run_service_template_launch_does_not_dispatch_when_link_persistence_fails(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        runtime_repository = RuntimeRepository(session_factory)
        event_hub = EventStreamHub(runtime_repository.list_events)
        failing_workflow_repository = FailingWorkflowRepository()
        run_service = RunService(
            runtime_repository,
            ImmediateFinishModelClient(),
            event_hub,
            workflow_repository=failing_workflow_repository,
        )

        with pytest.raises(RuntimeError, match="persist link failed"):
            await run_service.create_run_from_template_launch(
                tenant_id="tenant-a",
                objective="Triage incident INC-42",
                template_id="wf-triage",
                template_version=2,
                template_name="Incident Triage",
                launch_input={"ticket_id": "INC-42"},
                launch_metadata={"requested_by": "operator-a"},
                effective_workflow_policy={
                    "allowed_tools": ["rag_search"],
                    "approval_required_tools": [],
                    "default_kb_ids": ["kb-ops"],
                },
            )

        assert len(failing_workflow_repository.run_ids) == 1
        stored_run = await runtime_repository.get_run(failing_workflow_repository.run_ids[0])
        assert stored_run is not None
        assert stored_run.status.value == "failed"
        active_runs = await runtime_repository.list_active_runs()
        assert active_runs == []
        events = await runtime_repository.list_events(failing_workflow_repository.run_ids[0])
        assert [event.event_type.value for event in events] == ["run.created", "run.failed"]
        assert run_service._tasks == {}
    finally:
        await dispose_session_factory(session_factory)
