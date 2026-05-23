from __future__ import annotations

import pytest

from agent_runtime.domain.enums import RunStatus
from agent_runtime.domain.models import RunRecord
from agent_runtime.domain.models import ApprovalRequestRecord
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.runtime.services import RunService
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_assistant_service_creates_session_and_persists_chat_messages(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        repository = RuntimeRepository(session_factory)
        event_hub = EventStreamHub(repository.list_events)
        run_service = RunService(
            repository,
            ScriptedModelClient(
                {
                    "supervisor": [
                        ModelDecision(
                            kind=DecisionKind.FINISH,
                            summary="reply",
                            final_output="assistant says hello",
                        )
                    ]
                }
            ),
            event_hub,
        )

        from agent_runtime.assistant.repository import AssistantRepository
        from agent_runtime.assistant.service import AssistantService

        assistant_repository = AssistantRepository(session_factory)
        service = AssistantService(
            assistant_repository=assistant_repository,
            run_service=run_service,
        )

        session = await service.create_session(tenant_id="tenant-a", mode="chat", title="Chat A")
        response = await service.send_chat_message(
            tenant_id="tenant-a",
            session_id=session.session_id,
            content="hello",
        )
        fresh_repository = AssistantRepository(session_factory)
        fresh_service = AssistantService(
            assistant_repository=fresh_repository,
            run_service=run_service,
        )
        history = await fresh_service.list_messages(
            tenant_id="tenant-a",
            session_id=session.session_id,
        )

        assert session.tenant_id == "tenant-a"
        assert response.assistant_message.role == "assistant"
        assert response.assistant_message.content == "assistant says hello"
        assert response.status == "completed"
        assert [item.role for item in history] == ["user", "assistant"]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_assistant_service_creates_task_run_and_links_run_id(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        repository = RuntimeRepository(session_factory)
        event_hub = EventStreamHub(repository.list_events)
        run_service = RunService(
            repository,
            ScriptedModelClient(
                {
                    "supervisor": [
                        ModelDecision(
                            kind=DecisionKind.FINISH,
                            summary="done",
                            final_output="task completed",
                        )
                    ]
                }
            ),
            event_hub,
        )

        from agent_runtime.assistant.repository import AssistantRepository
        from agent_runtime.assistant.service import AssistantService

        assistant_repository = AssistantRepository(session_factory)
        service = AssistantService(
            assistant_repository=assistant_repository,
            run_service=run_service,
        )

        session = await service.create_session(tenant_id="tenant-a", mode="task", title="Task A")
        result = await service.create_task(
            tenant_id="tenant-a",
            session_id=session.session_id,
            objective="Investigate incident INC-1001",
            workflow_id="wf-1",
            version=3,
            launch_input={"incident_id": "INC-1001"},
        )
        activity = await service.get_activity(tenant_id="tenant-a", session_id=session.session_id)

        assert result.run_id is not None
        assert activity["linked_runs"][0]["run_id"] == result.run_id
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_assistant_service_uses_error_text_for_failed_chat_runs(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        from agent_runtime.assistant.repository import AssistantRepository
        from agent_runtime.assistant.service import AssistantService

        class FailingRunService:
            async def create_run(
                self,
                tenant_id: str,
                objective: str,
                initial_observations: list[str] | None = None,
            ) -> RunRecord:
                return RunRecord(tenant_id=tenant_id, objective=objective)

            async def resume_run(self, run_id: str) -> RunRecord:
                return RunRecord(
                    run_id=run_id,
                    tenant_id="tenant-a",
                    objective="hello",
                    status=RunStatus.FAILED,
                    error="model failed",
                )

            async def cancel_run(self, run_id: str) -> None:
                raise AssertionError("cancel_run should not be called on successful link persistence")

        assistant_repository = AssistantRepository(session_factory)
        service = AssistantService(
            assistant_repository=assistant_repository,
            run_service=FailingRunService(),
        )

        original_add_message = assistant_repository.add_message

        async def create_run_link(record):
            return record

        async def add_message(record):
            if record.role == "assistant":
                return record
            return await original_add_message(record)

        assistant_repository.create_run_link = create_run_link
        assistant_repository.add_message = add_message

        session = await service.create_session(tenant_id="tenant-a", mode="chat", title="Chat A")
        response = await service.send_chat_message(
            tenant_id="tenant-a",
            session_id=session.session_id,
            content="hello",
        )

        assert response.status == "failed"
        assert response.assistant_message.content == "model failed"
        assert response.assistant_message.structured_payload["run_status"] == "failed"
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_assistant_service_cancels_run_when_chat_link_persistence_fails(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)

        from agent_runtime.assistant.repository import AssistantRepository
        from agent_runtime.assistant.service import AssistantService

        class StubRunService:
            def __init__(self) -> None:
                self.cancelled_run_ids: list[str] = []

            async def create_run(
                self,
                tenant_id: str,
                objective: str,
                initial_observations: list[str] | None = None,
            ) -> RunRecord:
                return RunRecord(tenant_id=tenant_id, objective=objective)

            async def resume_run(self, run_id: str) -> RunRecord:
                raise AssertionError("resume_run should not be called when link persistence fails")

            async def cancel_run(self, run_id: str) -> None:
                self.cancelled_run_ids.append(run_id)

        assistant_repository = AssistantRepository(session_factory)
        run_service = StubRunService()
        service = AssistantService(
            assistant_repository=assistant_repository,
            run_service=run_service,
        )
        session = await service.create_session(tenant_id="tenant-a", mode="chat", title="Chat A")

        async def fail_create_run_link(*args, **kwargs):
            raise RuntimeError("link persistence failed")

        assistant_repository.create_run_link = fail_create_run_link

        with pytest.raises(RuntimeError, match="link persistence failed"):
            await service.send_chat_message(
                tenant_id="tenant-a",
                session_id=session.session_id,
                content="hello",
            )

        assert len(run_service.cancelled_run_ids) == 1
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_assistant_service_activity_includes_pending_approval_summary(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        repository = RuntimeRepository(session_factory)
        event_hub = EventStreamHub(repository.list_events)
        run_service = RunService(
            repository,
            ScriptedModelClient(
                {
                    "supervisor": [
                        ModelDecision(
                            kind=DecisionKind.FINISH,
                            summary="reply",
                            final_output="assistant says hello",
                        )
                    ]
                }
            ),
            event_hub,
        )

        from agent_runtime.assistant.repository import AssistantRepository
        from agent_runtime.assistant.service import AssistantService

        assistant_repository = AssistantRepository(session_factory)
        service = AssistantService(
            assistant_repository=assistant_repository,
            run_service=run_service,
            runtime_repository=repository,
        )

        session = await service.create_session(tenant_id="tenant-a", mode="task", title="Task A")
        result = await service.create_task(
            tenant_id="tenant-a",
            session_id=session.session_id,
            objective="Need approval",
        )
        await repository.create_approval_request(
            ApprovalRequestRecord(
                tenant_id="tenant-a",
                run_id=result.run_id,
                agent_id="agent-1",
                tool_name="rag_search",
                reason="Need approval for retrieval scope",
            )
        )

        activity = await service.get_activity(tenant_id="tenant-a", session_id=session.session_id)

        assert activity["linked_runs"][0]["run_id"] == result.run_id
        assert activity["linked_runs"][0]["pending_approval"] == {
            "approval_id": activity["linked_runs"][0]["pending_approval"]["approval_id"],
            "agent_id": "agent-1",
            "tool_name": "rag_search",
            "reason": "Need approval for retrieval scope",
            "created_at": activity["linked_runs"][0]["pending_approval"]["created_at"],
        }
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_assistant_service_passes_selected_kb_ids_into_chat_runs(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        repository = RuntimeRepository(session_factory)
        event_hub = EventStreamHub(repository.list_events)

        class RecordingRunService:
            def __init__(self) -> None:
                self.initial_observations: list[str] | None = None

            async def create_run(
                self,
                tenant_id: str,
                objective: str,
                initial_observations: list[str] | None = None,
            ) -> RunRecord:
                self.initial_observations = initial_observations
                return RunRecord(tenant_id=tenant_id, objective=objective)

            async def resume_run(self, run_id: str) -> RunRecord:
                return RunRecord(
                    run_id=run_id,
                    tenant_id="tenant-a",
                    objective="根据知识库回答 incident triage 的标准流程是什么？",
                    status=RunStatus.COMPLETED,
                    result="done",
                )

            async def cancel_run(self, run_id: str) -> None:
                raise AssertionError("cancel_run should not be called")

        from agent_runtime.assistant.repository import AssistantRepository
        from agent_runtime.assistant.service import AssistantService

        assistant_repository = AssistantRepository(session_factory)
        run_service = RecordingRunService()
        service = AssistantService(
            assistant_repository=assistant_repository,
            run_service=run_service,
        )

        async def create_run_link(record):
            return record

        original_add_message = assistant_repository.add_message

        async def add_message(record):
            if record.role == "assistant":
                return record
            return await original_add_message(record)

        assistant_repository.create_run_link = create_run_link
        assistant_repository.add_message = add_message

        session = await service.create_session(tenant_id="tenant-a", mode="chat", title="Chat A")
        await service.send_chat_message(
            tenant_id="tenant-a",
            session_id=session.session_id,
            content="根据知识库回答 incident triage 的标准流程是什么？",
            knowledge_base_ids=["kb-ops", "kb-runbook"],
        )

        assert run_service.initial_observations == [
            "Selected knowledge bases for retrieval: kb-ops, kb-runbook. Use these kb_ids when calling rag_search.",
        ]
    finally:
        await dispose_session_factory(session_factory)
