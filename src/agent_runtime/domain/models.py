from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_runtime.domain.enums import (
    AgentRole,
    AgentStatus,
    ApprovalStatus,
    EventType,
    RunStatus,
    TaskStatus,
    ToolInvocationStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    objective: str
    status: RunStatus = RunStatus.CREATED
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentRecord(BaseModel):
    agent_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    role: AgentRole
    status: AgentStatus = AgentStatus.CREATED
    objective: str
    observations: list[str] = Field(default_factory=list)
    parent_agent_id: str | None = None
    task_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    parent_agent_id: str
    worker_agent_id: str
    worker_role: AgentRole
    objective: str
    status: TaskStatus = TaskStatus.CREATED
    result: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CheckpointRecord(BaseModel):
    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    agent_id: str
    step_name: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)


class RuntimeEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    run_id: str
    event_type: EventType
    payload: dict[str, Any]
    agent_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def build(
        cls,
        *,
        tenant_id: str,
        run_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        agent_id: str | None = None,
    ) -> "RuntimeEvent":
        return cls(
            tenant_id=tenant_id,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
            agent_id=agent_id,
        )


class TenantPolicyRecord(BaseModel):
    tenant_id: str
    allowed_tools: list[str] = Field(default_factory=list)
    approval_required_tools: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolDefinitionRecord(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ApprovalRequestRecord(BaseModel):
    approval_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    run_id: str
    agent_id: str
    tool_name: str
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    resolution_note: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolInvocationRecord(BaseModel):
    invocation_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    run_id: str
    agent_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: ToolInvocationStatus = ToolInvocationStatus.CREATED
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowTemplateRecord(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int = 0
    latest_published_version: int | None = None
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowTemplateVersionRecord(BaseModel):
    template_id: str
    version: int
    definition: dict[str, Any]
    input_schema: dict[str, Any]
    source_version: int | None = None
    is_published: bool = False
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str | None = None


class WorkflowRunLinkRecord(BaseModel):
    run_id: str
    tenant_id: str
    template_id: str
    template_version: int
    template_name: str
    launch_input: dict[str, Any]
    launch_metadata: dict[str, Any] = Field(default_factory=dict)
    effective_workflow_policy: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeBaseRecord(BaseModel):
    kb_id: str
    tenant_id: str
    name: str
    root_path: str
    status: str
    embedding_provider_id: str
    index_provider_id: str
    chunking_strategy: str
    document_count: int = 0
    chunk_count: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentRecord(BaseModel):
    document_id: str = Field(default_factory=lambda: str(uuid4()))
    kb_id: str
    tenant_id: str
    relative_path: str
    content_hash: str
    file_type: str
    parse_status: str
    last_indexed_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkRecord(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid4()))
    document_id: str
    kb_id: str
    tenant_id: str
    chunk_index: int
    text: str
    text_length: int
    token_count: int
    source_locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalHitRecord(BaseModel):
    kb_id: str
    document_id: str
    chunk_id: str
    score: float
    text: str
    source_locator: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResponseRecord(BaseModel):
    hits: list[RetrievalHitRecord]
    compiled_context: str | None = None
    query_metadata: dict[str, Any] = Field(default_factory=dict)
