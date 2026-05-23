from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel

from agent_runtime.assistant.models import (
    AssistantMessageRecord,
    AssistantRunLinkRecord,
    AssistantSessionRecord,
)
from agent_runtime.assistant.repository import AssistantRepository
from agent_runtime.runtime.services import RunService
from agent_runtime.workflows.observability import WorkflowRunPendingApprovalSummary


class AssistantChatResult(BaseModel):
    user_message: AssistantMessageRecord
    assistant_message: AssistantMessageRecord
    run_id: str
    status: str


class AssistantTaskResult(BaseModel):
    request_message: AssistantMessageRecord
    run_id: str


class AssistantSessionNotFoundError(RuntimeError):
    pass


class AssistantValidationError(ValueError):
    pass


class AssistantService:
    def __init__(
        self,
        *,
        assistant_repository: AssistantRepository,
        run_service: RunService,
        workflow_service: Any | None = None,
        runtime_repository: Any | None = None,
    ) -> None:
        self._assistant_repository = assistant_repository
        self._run_service = run_service
        self._workflow_service = workflow_service
        self._runtime_repository = runtime_repository

    async def create_session(
        self,
        *,
        tenant_id: str,
        mode: Literal["chat", "task"] | str,
        title: str,
    ) -> AssistantSessionRecord:
        if mode not in {"chat", "task"}:
            raise AssistantValidationError("assistant mode must be 'chat' or 'task'")
        return await self._assistant_repository.create_session(
            AssistantSessionRecord(
                tenant_id=tenant_id,
                mode=mode,
                title=title,
            )
        )

    async def list_sessions(self, *, tenant_id: str) -> list[AssistantSessionRecord]:
        return await self._assistant_repository.list_sessions(tenant_id)

    async def list_messages(self, *, tenant_id: str, session_id: str) -> list[AssistantMessageRecord]:
        await self._require_session(tenant_id=tenant_id, session_id=session_id)
        return await self._assistant_repository.list_messages(tenant_id, session_id)

    async def send_chat_message(
        self,
        *,
        tenant_id: str,
        session_id: str,
        content: str,
        knowledge_base_ids: list[str] | None = None,
    ) -> AssistantChatResult:
        session = await self._require_session(tenant_id=tenant_id, session_id=session_id)
        user_message = await self._assistant_repository.add_message(
            AssistantMessageRecord(
                session_id=session.session_id,
                tenant_id=tenant_id,
                role="user",
                content=content,
            )
        )

        initial_observations = None
        if knowledge_base_ids:
            selected_ids = ", ".join(knowledge_base_ids)
            initial_observations = [
                f"Selected knowledge bases for retrieval: {selected_ids}. Use these kb_ids when calling rag_search.",
            ]

        run = await self._run_service.create_run(
            tenant_id=tenant_id,
            objective=content,
            initial_observations=initial_observations,
        )
        try:
            await self._assistant_repository.create_run_link(
                AssistantRunLinkRecord(
                    session_id=session.session_id,
                    message_id=user_message.message_id,
                    run_id=run.run_id,
                    launch_kind="chat",
                )
            )
        except Exception:
            await self._cancel_run_best_effort(run.run_id)
            raise
        run = await self._run_service.resume_run(run.run_id)

        assistant_message = await self._assistant_repository.add_message(
            AssistantMessageRecord(
                session_id=session.session_id,
                tenant_id=tenant_id,
                role="assistant",
                content=run.result or run.error or "",
                run_id=run.run_id,
                structured_payload={
                    "run_id": run.run_id,
                    "run_status": run.status.value,
                    "error": run.error,
                },
            )
        )
        return AssistantChatResult(
            user_message=user_message,
            assistant_message=assistant_message,
            run_id=run.run_id,
            status=run.status.value,
        )

    async def create_task(
        self,
        *,
        tenant_id: str,
        session_id: str,
        objective: str,
        workflow_id: str | None = None,
        version: int | None = None,
        launch_input: dict[str, object] | None = None,
    ) -> AssistantTaskResult:
        session = await self._require_session(tenant_id=tenant_id, session_id=session_id)
        request_message = await self._assistant_repository.add_message(
            AssistantMessageRecord(
                session_id=session.session_id,
                tenant_id=tenant_id,
                role="user",
                content=objective,
                structured_payload={"kind": "task_request"},
            )
        )
        run, launch_kind = await self._launch_task_run(
            tenant_id=tenant_id,
            objective=objective,
            workflow_id=workflow_id,
            version=version,
            launch_input=launch_input,
            session_id=session.session_id,
            message_id=request_message.message_id,
        )
        try:
            await self._assistant_repository.create_run_link(
                AssistantRunLinkRecord(
                    session_id=session.session_id,
                    message_id=request_message.message_id,
                    run_id=run.run_id,
                    launch_kind=launch_kind,
                )
            )
        except Exception:
            await self._cancel_run_best_effort(run.run_id)
            raise
        return AssistantTaskResult(
            request_message=request_message,
            run_id=run.run_id,
        )

    async def get_activity(self, *, tenant_id: str, session_id: str) -> dict[str, list[dict[str, Any]]]:
        await self._require_session(tenant_id=tenant_id, session_id=session_id)
        messages = await self._assistant_repository.list_messages(tenant_id, session_id)
        run_links = await self._assistant_repository.list_run_links(tenant_id, session_id)
        run_ids = [link.run_id for link in run_links]
        approvals_by_run_id = (
            await self._runtime_repository.list_pending_approvals_by_run_ids(run_ids)
            if self._runtime_repository is not None
            else {}
        )

        linked_runs: list[dict[str, Any]] = []
        for link in run_links:
            run = await self._run_service.get_run(link.run_id)
            pending_approval = self._get_pending_approval_summary(
                run_id=link.run_id,
                approvals_by_run_id=approvals_by_run_id,
            )
            linked_runs.append(
                {
                    "link_id": link.link_id,
                    "message_id": link.message_id,
                    "run_id": link.run_id,
                    "launch_kind": link.launch_kind,
                    "created_at": link.created_at,
                    "run_status": run.status.value,
                    "objective": run.objective,
                    "result": run.result,
                    "error": run.error,
                    "pending_approval": None
                    if pending_approval is None
                    else pending_approval.model_dump(mode="json"),
                }
            )

        return {
            "messages": [message.model_dump(mode="json") for message in messages],
            "linked_runs": linked_runs,
        }

    async def _require_session(self, *, tenant_id: str, session_id: str) -> AssistantSessionRecord:
        session = await self._assistant_repository.get_session(tenant_id, session_id)
        if session is None:
            raise AssistantSessionNotFoundError(f"assistant session not found: {session_id}")
        return session

    async def _launch_task_run(
        self,
        *,
        tenant_id: str,
        objective: str,
        workflow_id: str | None,
        version: int | None,
        launch_input: dict[str, object] | None,
        session_id: str,
        message_id: str,
    ) -> tuple[Any, str]:
        if workflow_id is not None and self._workflow_service is not None:
            run, _ = await self._workflow_service.launch_template(
                tenant_id=tenant_id,
                template_id=workflow_id,
                version=version,
                launch_input=launch_input or {},
                metadata={
                    "assistant_session_id": session_id,
                    "assistant_message_id": message_id,
                },
            )
            return run, "workflow"

        run = await self._run_service.create_run(tenant_id=tenant_id, objective=objective)
        return run, "task"

    async def _cancel_run_best_effort(self, run_id: str) -> None:
        try:
            await self._run_service.cancel_run(run_id)
        except Exception:
            return

    @staticmethod
    def _get_pending_approval_summary(
        *,
        run_id: str,
        approvals_by_run_id: dict[str, list[Any]],
    ) -> WorkflowRunPendingApprovalSummary | None:
        pending_approvals = approvals_by_run_id.get(run_id, [])
        if not pending_approvals:
            return None

        approval = pending_approvals[0]
        return WorkflowRunPendingApprovalSummary(
            approval_id=approval.approval_id,
            agent_id=approval.agent_id,
            tool_name=approval.tool_name,
            reason=approval.reason,
            created_at=approval.created_at,
        )
