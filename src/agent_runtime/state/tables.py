from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UtcDateTime requires timezone-aware datetimes")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def process_result_value(self, value: str | None, dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class Base(DeclarativeBase):
    pass


class RunTable(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    objective: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class AgentTable(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    objective: Mapped[str] = mapped_column(Text())
    observations: Mapped[list[str]] = mapped_column(JSON)
    parent_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.agent_id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.task_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class TaskTable(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    parent_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    worker_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    worker_role: Mapped[str] = mapped_column(String(32))
    objective: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class EventTable(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.agent_id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)


class CheckpointTable(Base):
    __tablename__ = "checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    step_name: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)


class TenantPolicyTable(Base):
    __tablename__ = "tenant_policies"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON)
    approval_required_tools: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class ToolDefinitionTable(Base):
    __tablename__ = "tool_definitions"

    tool_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(Text())
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    requires_approval: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class ApprovalRequestTable(Base):
    __tablename__ = "approval_requests"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class ToolInvocationTable(Base):
    __tablename__ = "tool_invocations"

    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class WorkflowTemplateTable(Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_id", name="uq_workflow_templates_tenant_template"),
    )

    template_pk: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    latest_version: Mapped[int]
    latest_published_version: Mapped[int | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class WorkflowTemplateVersionTable(Base):
    __tablename__ = "workflow_template_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["workflow_templates.tenant_id", "workflow_templates.template_id"],
            name="fk_workflow_template_versions_template",
        ),
        UniqueConstraint("tenant_id", "template_id", "version", name="uq_workflow_template_versions"),
    )

    version_pk: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int]
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_version: Mapped[int | None] = mapped_column(nullable=True)
    is_published: Mapped[bool] = mapped_column(index=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorkflowRunLinkTable(Base):
    __tablename__ = "workflow_run_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["workflow_templates.tenant_id", "workflow_templates.template_id"],
            name="fk_workflow_run_links_template",
        ),
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    template_version: Mapped[int]
    template_name: Mapped[str] = mapped_column(String(256))
    launch_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    launch_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    effective_workflow_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)


class AssistantSessionTable(Base):
    __tablename__ = "assistant_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)


class AssistantMessageTable(Base):
    __tablename__ = "assistant_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assistant_sessions.session_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text())
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)


class AssistantRunLinkTable(Base):
    __tablename__ = "assistant_run_links"

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assistant_sessions.session_id"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("assistant_messages.message_id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    launch_kind: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)


class KnowledgeBaseTable(Base):
    __tablename__ = "knowledge_bases"

    kb_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    root_path: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    embedding_provider_id: Mapped[str] = mapped_column(String(128))
    index_provider_id: Mapped[str] = mapped_column(String(128))
    chunking_strategy: Mapped[str] = mapped_column(String(128))
    document_count: Mapped[int]
    chunk_count: Mapped[int]
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class KnowledgeDocumentTable(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("kb_id", "relative_path", name="uq_knowledge_documents_kb_path"),)

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.kb_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    relative_path: Mapped[str] = mapped_column(Text())
    content_hash: Mapped[str] = mapped_column(String(128))
    file_type: Mapped[str] = mapped_column(String(32))
    parse_status: Mapped[str] = mapped_column(String(32), index=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)


class KnowledgeChunkTable(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),)

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.document_id"), index=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.kb_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    chunk_index: Mapped[int]
    text: Mapped[str] = mapped_column(Text())
    text_length: Mapped[int]
    token_count: Mapped[int]
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
