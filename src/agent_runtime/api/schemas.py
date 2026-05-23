from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class CreateRunRequest(BaseModel):
    tenant_id: str
    objective: str


class RunResponse(BaseModel):
    run_id: str
    tenant_id: str
    objective: str
    status: str
    result: str | None
    error: str | None


class ActionAcceptedResponse(BaseModel):
    status: str


class KnowledgeBaseCreateRequest(BaseModel):
    kb_id: str
    tenant_id: str
    name: str
    root_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseResponse(BaseModel):
    kb_id: str
    tenant_id: str
    name: str
    root_path: str
    status: str
    document_count: int
    chunk_count: int
    last_error: str | None


class EventReplayResponse(BaseModel):
    events: list[dict]


class ToolDefinitionRequest(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool = False


class ToolDefinitionResponse(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool


class TenantPolicyRequest(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list)
    approval_required_tools: list[str] = Field(default_factory=list)


class TenantPolicyResponse(BaseModel):
    tenant_id: str
    allowed_tools: list[str]
    approval_required_tools: list[str]


class ApprovalActionRequest(BaseModel):
    resolution_note: str | None = None


class ApprovalResponse(BaseModel):
    approval_id: str
    tenant_id: str
    run_id: str
    agent_id: str
    tool_name: str
    reason: str
    status: str
    resolution_note: str | None


class WorkflowTemplateCreateRequest(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class WorkflowTemplatePublishRequest(BaseModel):
    tenant_id: str


class WorkflowTemplateLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    version: int | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTemplateResponse(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int


class WorkflowTemplateLaunchResponse(RunResponse):
    workflow_template: dict[str, Any]


class WorkflowCreateRequest(BaseModel):
    workflow_id: str
    tenant_id: str
    name: str
    description: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class WorkflowPublishRequest(BaseModel):
    tenant_id: str


class WorkflowLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    version: int | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowVersionCreateRequest(BaseModel):
    tenant_id: str
    created_by: str | None = None


class WorkflowVersionUpdateRequest(BaseModel):
    tenant_id: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)


class WorkflowArchiveRequest(BaseModel):
    tenant_id: str


class WorkflowResponse(BaseModel):
    workflow_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int
    latest_published_version: int | None = None
    archived_at: datetime | None = None


class WorkflowListItemResponse(BaseModel):
    workflow_id: str
    tenant_id: str
    name: str
    status: str
    latest_version: int


class WorkflowListResponse(BaseModel):
    items: list[WorkflowListItemResponse] = Field(default_factory=list)
    next_cursor: str | None = None


class WorkflowVersionResponse(BaseModel):
    version: int
    definition: dict[str, Any]
    input_schema: dict[str, Any]
    source_version: int | None = None
    is_published: bool
    created_by: str | None = None


class WorkflowVersionSummaryResponse(BaseModel):
    version: int
    status: str
    is_published: bool
    source_version: int | None = None
    created_by: str | None = None


class WorkflowDetailResponse(WorkflowResponse):
    created_at: datetime
    updated_at: datetime
    latest_draft: WorkflowVersionResponse | None = None
    latest_published: WorkflowVersionResponse | None = None
    version_summaries: list[WorkflowVersionSummaryResponse] = Field(default_factory=list)


class WorkflowLaunchResponse(RunResponse):
    workflow: dict[str, Any]


class WorkflowRunPendingApprovalSummaryResponse(BaseModel):
    approval_id: str
    agent_id: str
    tool_name: str
    reason: str
    created_at: datetime


class WorkflowRunObservationListItemResponse(BaseModel):
    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_name: str
    template_version: int
    status: str
    current_blocking_state: str
    current_blocking_state_reason: str | None = None
    latest_failure_summary: str | None = None
    latest_checkpoint_step: str | None = None
    started_at: datetime
    last_updated_at: datetime
    pending_approval: WorkflowRunPendingApprovalSummaryResponse | None = None


class WorkflowRunObservationListResponse(BaseModel):
    items: list[WorkflowRunObservationListItemResponse] = Field(default_factory=list)
    next_cursor: str | None = None


class WorkflowRunObservationWorkflowResponse(BaseModel):
    workflow_id: str
    workflow_name: str
    template_version: int
    launch_input: dict[str, Any] = Field(default_factory=dict)
    launch_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunObservationDetailResponse(BaseModel):
    run: dict[str, Any]
    workflow: WorkflowRunObservationWorkflowResponse
    agents: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    latest_checkpoint: dict[str, Any] | None = None
    pending_approval: WorkflowRunPendingApprovalSummaryResponse | None = None
    current_blocking_state: str
    latest_failure_summary: str | None = None


class WorkflowTemplateVersionCreateRequest(BaseModel):
    tenant_id: str
    created_by: str | None = None


class WorkflowTemplateVersionUpdateRequest(BaseModel):
    tenant_id: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)


class WorkflowTemplateArchiveRequest(BaseModel):
    tenant_id: str


class WorkflowTemplateVersionResponse(BaseModel):
    version: int
    definition: dict[str, Any]
    input_schema: dict[str, Any]
    source_version: int | None = None
    is_published: bool
    created_by: str | None = None


class WorkflowTemplateVersionSummaryResponse(BaseModel):
    version: int
    status: str
    is_published: bool
    source_version: int | None = None
    created_by: str | None = None


class WorkflowTemplateDetailResponse(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int
    latest_published_version: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    latest_draft: WorkflowTemplateVersionResponse | None = None
    latest_published: WorkflowTemplateVersionResponse | None = None
    version_summaries: list[WorkflowTemplateVersionSummaryResponse] = Field(default_factory=list)


class WorkflowTemplateLifecycleResponse(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int
    latest_published_version: int | None = None
    archived_at: datetime | None = None


class AssistantSessionCreateRequest(BaseModel):
    tenant_id: str
    mode: Literal["chat", "task"]
    title: str


class AssistantSessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    title: str
    mode: Literal["chat", "task"]
    status: str
    created_at: datetime
    updated_at: datetime


class AssistantMessageResponse(BaseModel):
    message_id: str
    session_id: str
    tenant_id: str
    role: str
    content: str
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    created_at: datetime


class AssistantChatRequest(BaseModel):
    tenant_id: str
    content: str
    knowledge_base_ids: list[str] = Field(default_factory=list)


class AssistantChatResponse(BaseModel):
    user_message: AssistantMessageResponse
    assistant_message: AssistantMessageResponse
    run_id: str
    status: str


class AssistantTaskCreateRequest(BaseModel):
    tenant_id: str
    objective: str
    workflow_id: str | None = None
    version: int | None = None
    launch_input: dict[str, Any] = Field(default_factory=dict)


class AssistantTaskResponse(BaseModel):
    request_message: AssistantMessageResponse
    run_id: str


class AssistantActivityLinkedRunResponse(BaseModel):
    link_id: str
    message_id: str
    run_id: str
    launch_kind: str
    created_at: datetime
    run_status: str
    objective: str
    result: str | None
    error: str | None
    pending_approval: WorkflowRunPendingApprovalSummaryResponse | None = None


class AssistantActivityResponse(BaseModel):
    messages: list[AssistantMessageResponse] = Field(default_factory=list)
    linked_runs: list[AssistantActivityLinkedRunResponse] = Field(default_factory=list)
