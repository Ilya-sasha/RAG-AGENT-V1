from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from agent_runtime.agents.profiles import ensure_predefined_worker
from agent_runtime.domain.enums import AgentRole
from agent_runtime.domain.models import WorkflowTemplateRecord, WorkflowTemplateVersionRecord
from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.runtime.services import RunService
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.workflows.assembler import AssembledTemplateLaunch, assemble_template_launch
from agent_runtime.workflows.repository import WorkflowRepository


class WorkflowTemplateValidationError(ValueError):
    pass


class WorkflowTemplateLaunchGuardrailError(WorkflowTemplateValidationError):
    pass


class WorkflowTemplatePreflightError(WorkflowTemplateValidationError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class WorkflowTemplateConflictError(RuntimeError):
    pass


class WorkflowTemplateNotFoundError(RuntimeError):
    pass


WORKFLOW_LIST_LIMIT_DEFAULT = 20
WORKFLOW_LIST_LIMIT_MAX = 100


def validate_template_definition(definition: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    objective_template = definition.get("entrypoint", {}).get("objective_template")
    if not isinstance(objective_template, str) or not objective_template.strip():
        errors.append("entrypoint.objective_template must be a non-empty string")

    worker_roles = definition.get("agents", {}).get("allowed_worker_roles", [])
    for worker_role in worker_roles:
        try:
            ensure_predefined_worker(AgentRole(worker_role))
        except Exception:
            errors.append(f"unsupported worker role: {worker_role}")

    for path, value in (
        ("agents.max_worker_count", definition.get("agents", {}).get("max_worker_count")),
        ("runtime.max_turns", definition.get("runtime", {}).get("max_turns")),
        ("runtime.timeout_seconds", definition.get("runtime", {}).get("timeout_seconds")),
    ):
        if value is None:
            continue
        if not isinstance(value, int) or value < 0:
            errors.append(f"{path} must be non-negative")

    duplicate_tool_names = _find_duplicates(definition.get("tools", {}).get("allowed_tools", []))
    if duplicate_tool_names:
        errors.append(
            f"tools.allowed_tools contains duplicate entries: {', '.join(duplicate_tool_names)}"
        )

    duplicate_kb_ids = _find_duplicates(definition.get("knowledge", {}).get("default_kb_ids", []))
    if duplicate_kb_ids:
        errors.append(
            f"knowledge.default_kb_ids contains duplicate entries: {', '.join(duplicate_kb_ids)}"
        )

    return errors


def _find_duplicates(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        if value in seen and value not in duplicates:
            duplicates.append(value)
            continue
        seen.add(value)
    return duplicates


def _dedupe_sorted_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({value for value in values if isinstance(value, str)})


class WorkflowService:
    def __init__(
        self,
        *,
        workflow_repository: WorkflowRepository,
        runtime_repository: RuntimeRepository,
        knowledge_repository: KnowledgeRepository,
        run_service: RunService,
    ) -> None:
        self._repository = workflow_repository
        self._runtime_repository = runtime_repository
        self._knowledge_repository = knowledge_repository
        self._run_service = run_service

    @property
    def repository(self) -> WorkflowRepository:
        return self._repository

    async def create_template(
        self,
        *,
        template_id: str,
        tenant_id: str,
        name: str,
        description: str,
        definition: dict[str, Any],
        input_schema: dict[str, Any],
        created_by: str | None = None,
    ) -> WorkflowTemplateRecord:
        errors = validate_template_definition(definition)
        if errors:
            raise WorkflowTemplateValidationError("; ".join(errors))
        self._validate_workflow_input_schema(input_schema)

        existing_template = await self._repository.get_template(tenant_id, template_id)
        if existing_template is not None:
            raise WorkflowTemplateConflictError(f"workflow template already exists: {tenant_id}/{template_id}")

        template = WorkflowTemplateRecord(
            template_id=template_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            status="draft",
            latest_version=1,
        )
        version = WorkflowTemplateVersionRecord(
            template_id=template_id,
            version=1,
            definition=definition,
            input_schema=input_schema,
            created_by=created_by,
        )
        try:
            await self._repository.create_template(template, version)
        except IntegrityError as exc:
            raise WorkflowTemplateConflictError(
                f"workflow template already exists: {tenant_id}/{template_id}"
            ) from exc
        return template

    async def list_templates(self, tenant_id: str) -> list[WorkflowTemplateRecord]:
        return await self._repository.list_templates(tenant_id)

    async def list_workflows(
        self,
        *,
        tenant_id: str,
        workflow_id_prefix: str | None,
        name_query: str | None,
        limit: int | None,
        cursor: str | None,
    ) -> dict[str, object]:
        effective_limit = WORKFLOW_LIST_LIMIT_DEFAULT if limit is None else limit
        if (
            isinstance(effective_limit, bool)
            or not isinstance(effective_limit, int)
            or effective_limit < 1
            or effective_limit > WORKFLOW_LIST_LIMIT_MAX
        ):
            raise WorkflowTemplateValidationError("limit must be between 1 and 100")
        try:
            return await self._repository.list_workflow_summaries(
                tenant_id=tenant_id,
                workflow_id_prefix=workflow_id_prefix,
                name_query=name_query,
                limit=effective_limit,
                cursor=cursor,
            )
        except ValueError as exc:
            if str(exc) != "invalid workflow list cursor":
                raise
            raise WorkflowTemplateValidationError("invalid workflow list cursor") from exc

    async def get_template_detail(self, tenant_id: str, template_id: str) -> dict[str, Any]:
        template = await self._repository.get_template(tenant_id, template_id)
        if template is None:
            raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
        latest_draft = await self._repository.get_draft_version(tenant_id, template_id)
        latest_published = await self._repository.get_latest_published_version(tenant_id, template_id)
        version_summaries = await self._repository.list_template_versions(tenant_id, template_id)
        return {
            "template": template,
            "latest_draft": latest_draft,
            "latest_published": latest_published,
            "version_summaries": version_summaries,
        }

    async def create_template_version_draft(
        self,
        *,
        tenant_id: str,
        template_id: str,
        created_by: str | None = None,
    ) -> WorkflowTemplateVersionRecord:
        template = await self._repository.get_template(tenant_id, template_id)
        if template is None:
            raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
        try:
            return await self._repository.create_copied_draft_version(
                tenant_id,
                template_id,
                created_by=created_by,
            )
        except ValueError as exc:
            raise WorkflowTemplateConflictError(str(exc)) from exc

    async def replace_template_version_draft(
        self,
        *,
        tenant_id: str,
        template_id: str,
        version: int,
        definition: dict[str, Any],
        input_schema: dict[str, Any],
    ) -> WorkflowTemplateVersionRecord:
        version_record = await self._repository.get_template_version(tenant_id, template_id, version)
        if version_record is None:
            raise WorkflowTemplateNotFoundError(f"workflow template version not found: {template_id}:{version}")

        errors = validate_template_definition(definition)
        if errors:
            raise WorkflowTemplateValidationError("; ".join(errors))
        self._validate_workflow_input_schema(input_schema)

        try:
            return await self._repository.replace_draft_version(
                tenant_id=tenant_id,
                template_id=template_id,
                version=version,
                definition=definition,
                input_schema=input_schema,
            )
        except ValueError as exc:
            raise WorkflowTemplateValidationError(str(exc)) from exc

    async def delete_template_version(
        self,
        *,
        tenant_id: str,
        template_id: str,
        version: int,
    ) -> None:
        version_record = await self._repository.get_template_version(tenant_id, template_id, version)
        if version_record is None:
            raise WorkflowTemplateNotFoundError(f"workflow template version not found: {template_id}:{version}")
        if version_record.is_published:
            raise WorkflowTemplateValidationError(
                f"cannot delete published workflow template version: {template_id}:{version}"
            )
        try:
            await self._repository.delete_draft_version(tenant_id, template_id, version)
        except ValueError as exc:
            raise WorkflowTemplateValidationError(str(exc)) from exc

    async def archive_template(self, tenant_id: str, template_id: str) -> WorkflowTemplateRecord:
        template = await self._repository.get_template(tenant_id, template_id)
        if template is None:
            raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
        if template.latest_published_version is None:
            raise WorkflowTemplateValidationError(f"cannot archive unpublished workflow template: {template_id}")
        archived = await self._repository.archive_template(tenant_id, template_id)
        return archived

    async def publish_template_version(
        self,
        *,
        tenant_id: str,
        template_id: str,
        version: int,
    ) -> WorkflowTemplateRecord:
        template = await self._repository.get_template(tenant_id, template_id)
        if template is None:
            raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")

        version_record = await self._repository.get_template_version(tenant_id, template_id, version)
        if version_record is None:
            raise WorkflowTemplateNotFoundError(f"workflow template version not found: {template_id}:{version}")

        tenant_policy = await self._runtime_repository.get_tenant_policy(tenant_id)
        knowledge_bases = await self._knowledge_repository.list_knowledge_bases(tenant_id)
        errors = self._collect_publish_preflight_errors(
            tenant_id=tenant_id,
            template_id=template_id,
            version=version,
            version_record=version_record,
            definition=version_record.definition,
            input_schema=version_record.input_schema,
            tenant_allowed_tools=tenant_policy.allowed_tools if tenant_policy is not None else None,
            existing_kb_ids=[item.kb_id for item in knowledge_bases],
        )
        if errors:
            raise WorkflowTemplatePreflightError(errors)

        await self._repository.publish_version(tenant_id, template_id, version)
        published_template = await self._repository.get_template(tenant_id, template_id)
        if published_template is None:
            raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
        return published_template

    async def launch_template(
        self,
        *,
        tenant_id: str,
        template_id: str,
        version: int | None,
        launch_input: dict[str, Any],
        metadata: dict[str, Any],
    ):
        template = await self._repository.get_template(tenant_id, template_id)
        if template is None:
            raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")

        if version is None:
            version_record = await self._repository.get_latest_published_version(tenant_id, template_id)
            if version_record is None:
                raise WorkflowTemplateValidationError(
                    f"workflow template has no published version: {template_id}"
                )
        else:
            version_record = await self._repository.get_template_version(tenant_id, template_id, version)
            if version_record is None:
                raise WorkflowTemplateNotFoundError(
                    f"workflow template version not found: {template_id}:{version}"
                )
            if not version_record.is_published:
                raise WorkflowTemplateValidationError(
                    f"workflow template version is not published: {template_id}:{version}"
                )

        self._validate_template_launch_input(version_record.input_schema, launch_input)

        tenant_policy = await self._runtime_repository.get_tenant_policy(tenant_id)
        if tenant_policy is None:
            raise WorkflowTemplateNotFoundError(f"tenant policy not found: {tenant_id}")

        knowledge_bases = await self._knowledge_repository.list_knowledge_bases(tenant_id)
        try:
            assembled = assemble_template_launch(
                tenant_id=tenant_id,
                template_id=template_id,
                template_name=template.name,
                version=version_record.version,
                definition=version_record.definition,
                launch_input=launch_input,
                tenant_allowed_tools=tenant_policy.allowed_tools,
                tenant_approval_required_tools=tenant_policy.approval_required_tools,
                existing_kb_ids=[item.kb_id for item in knowledge_bases],
            )
        except ValueError as exc:
            raise WorkflowTemplateLaunchGuardrailError(str(exc)) from exc
        run = await self._run_service.create_run_from_template_launch(
            tenant_id=tenant_id,
            objective=assembled.objective,
            template_id=template_id,
            template_version=version_record.version,
            template_name=template.name,
            launch_input=launch_input,
            launch_metadata=metadata,
            effective_workflow_policy=assembled.workflow_policy,
        )
        return run, {
            "template_id": template_id,
            "version": version_record.version,
            "name": template.name,
        }

    @staticmethod
    def _validate_template_launch_input(input_schema: dict[str, Any], launch_input: dict[str, Any]) -> None:
        if not input_schema:
            return
        if input_schema.get("type") != "object":
            raise WorkflowTemplateValidationError("workflow template input_schema must declare type=object")

        required_fields = input_schema.get("required", [])
        if not isinstance(required_fields, list):
            raise WorkflowTemplateValidationError("workflow template input_schema required must be a list")

        missing_fields = [field for field in required_fields if isinstance(field, str) and field not in launch_input]
        if missing_fields:
            missing_fields_text = ", ".join(sorted(missing_fields))
            raise WorkflowTemplateValidationError(
                f"workflow template launch input missing required fields: {missing_fields_text}"
            )

    @staticmethod
    def _validate_workflow_input_schema(input_schema: dict[str, Any]) -> None:
        if not input_schema:
            return
        if input_schema.get("type") != "object":
            raise WorkflowTemplateValidationError("input_schema must declare type=object")

        required_fields = input_schema.get("required", [])
        if not isinstance(required_fields, list):
            raise WorkflowTemplateValidationError("input_schema required must be a list")

    @classmethod
    def _collect_publish_preflight_errors(
        cls,
        *,
        tenant_id: str,
        template_id: str,
        version: int,
        version_record: WorkflowTemplateVersionRecord,
        definition: dict[str, Any],
        input_schema: dict[str, Any],
        tenant_allowed_tools: list[str] | None,
        existing_kb_ids: list[str],
    ) -> list[str]:
        errors: list[str] = []
        if version_record.is_published:
            errors.append(f"workflow template version is not eligible for publish: {template_id}:{version}")
        if tenant_allowed_tools is None:
            errors.append(f"tenant policy not found: {tenant_id}")

        errors.extend(validate_template_definition(definition))
        try:
            cls._validate_workflow_input_schema(input_schema)
        except WorkflowTemplateValidationError as exc:
            errors.append(str(exc))

        template_allowed_tools = definition.get("tools", {}).get("allowed_tools", [])
        if tenant_allowed_tools is not None and isinstance(template_allowed_tools, list):
            disallowed_tools = _dedupe_sorted_strings(
                [
                    tool
                    for tool in template_allowed_tools
                    if isinstance(tool, str) and tool not in tenant_allowed_tools
                ]
            )
            if disallowed_tools:
                errors.append(f"template tools exceed tenant policy: {', '.join(disallowed_tools)}")

        default_kb_ids = definition.get("knowledge", {}).get("default_kb_ids", [])
        if isinstance(default_kb_ids, list):
            missing_kb_ids = _dedupe_sorted_strings(
                [
                    kb_id
                    for kb_id in default_kb_ids
                    if isinstance(kb_id, str) and kb_id not in existing_kb_ids
                ]
            )
            if missing_kb_ids:
                errors.append(f"unknown knowledge base: {', '.join(missing_kb_ids)}")

        return errors


__all__ = [
    "AssembledTemplateLaunch",
    "WorkflowTemplateConflictError",
    "WorkflowTemplateLaunchGuardrailError",
    "WorkflowTemplateNotFoundError",
    "WorkflowTemplatePreflightError",
    "WorkflowTemplateValidationError",
    "WorkflowService",
    "assemble_template_launch",
    "validate_template_definition",
]
