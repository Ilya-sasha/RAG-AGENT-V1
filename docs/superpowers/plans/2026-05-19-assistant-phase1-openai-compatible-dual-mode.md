# Assistant Phase 1 OpenAI-Compatible Dual-Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current runtime into a usable tool-type assistant by adding an OpenAI-compatible model provider, persisted assistant sessions/messages, assistant APIs, and a dedicated `/assistant` dual-mode workspace.

**Architecture:** Keep the existing runtime as the only execution kernel. Add a thin assistant product layer above `RunService`, introduce assistant persistence tables and repositories, implement a real compatible-provider `ModelClient`, and expose a dedicated `/assistant` workspace that supports both chat and task mode while reusing the current tool gateway, approvals, RAG, and workflow/run observability surfaces.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite, httpx, existing SSE event streaming, existing admin static-asset pattern, pytest, pytest-asyncio

---

## File Structure

### Create

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\__init__.py`
  Assistant package marker and exports.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\models.py`
  Assistant-side record models such as sessions, messages, and session activity projections.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\repository.py`
  Assistant persistence repository for sessions, messages, and links.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\service.py`
  Assistant application layer for chat mode, task mode, activity aggregation, and runtime bridging.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\models\openai_compatible.py`
  Real compatible-provider implementation of `ModelClient`.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\assistant.py`
  Assistant API routes for sessions, messages, chat, tasks, and activity.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\static\assistant\index.html`
  Dedicated user-facing assistant workspace.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\static\assistant\assistant.css`
  Assistant workspace styling.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\static\assistant\assistant.js`
  Assistant workspace behavior for session list, mode switch, chat submit, task submit, activity refresh, and approval actions.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\assistant_ui.py`
  Minimal route that serves `/assistant`.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_openai_compatible_model_client.py`
  Provider unit coverage.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_assistant_service.py`
  Assistant application-layer unit coverage.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_assistant_api.py`
  Assistant route and persistence coverage.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_assistant_ui.py`
  `/assistant` page and static asset coverage.

- `C:\Users\Ilya\PycharmProjects\AGENT\docs\assistant-deepseek-validation.md`
  Manual DeepSeek compatibility validation checklist and result template.

### Modify

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\tables.py`
  Add assistant persistence tables.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\db.py`
  Add additive schema upgrade helpers for assistant tables if needed.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\domain\models.py`
  Add assistant-side record classes if they belong in the shared domain layer; otherwise leave runtime domain untouched and keep assistant models isolated.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
  Add assistant request and response schemas.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
  Wire assistant service, assistant routes, assistant UI route, static asset mount, and provider configuration.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\models\base.py`
  Extend provider-facing model abstractions only if necessary to represent assistant-compatible tool-call decisions without breaking current runtime behavior.

- `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
  Add `/assistant` startup and usage entrypoint.

- `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`
  Add assistant workspace usage guidance and DeepSeek validation reference.

### Reused Without Structural Changes

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\runtime\services.py`
- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\runtime\orchestrator.py`
- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\tools\gateway.py`
- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\runs.py`
- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\approvals.py`
- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_runs.py`
- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\knowledge_bases.py`

### Verification Commands

- Assistant provider and service units:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_openai_compatible_model_client.py tests\unit\test_assistant_service.py -v`

- Assistant API and UI integration:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_assistant_api.py tests\integration\test_assistant_ui.py -v`

- Existing affected regressions:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_app_smoke.py tests\integration\test_workflow_runs_api.py tests\integration\test_workflows_api.py tests\integration\test_knowledge_bases_api.py -v`

- Full regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`

---

### Task 1: Add Red Tests For Assistant Persistence And Application Boundaries

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_assistant_service.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\__init__.py`

- [ ] **Step 1: Write failing assistant service tests for session creation, message persistence, and task linkage**

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.runtime.services import RunService


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
        history = await service.list_messages(tenant_id="tenant-a", session_id=session.session_id)

        assert session.tenant_id == "tenant-a"
        assert response.assistant_message.role == "assistant"
        assert response.assistant_message.content == "assistant says hello"
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
        )
        activity = await service.get_activity(tenant_id="tenant-a", session_id=session.session_id)

        assert result.run_id is not None
        assert activity["linked_runs"][0]["run_id"] == result.run_id
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 2: Run the assistant service tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_assistant_service.py -v`
Expected: FAIL because `agent_runtime.assistant` modules do not exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_assistant_service.py src/agent_runtime/assistant/__init__.py
git commit -m "test: add assistant service red coverage"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 2: Add Red Tests For OpenAI-Compatible Provider Behavior

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_openai_compatible_model_client.py`

- [ ] **Step 1: Write failing provider tests for finish decisions, tool-call decisions, and provider errors**

```python
from __future__ import annotations

import httpx
import pytest

from agent_runtime.domain.enums import AgentRole, DecisionKind
from agent_runtime.models.base import ModelTurnInput


@pytest.mark.asyncio
async def test_openai_compatible_client_maps_finish_response_to_model_decision() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "final answer",
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        decision = await client.complete(
            ModelTurnInput(
                run_id="run-1",
                agent_id="agent-1",
                agent_role=AgentRole.SUPERVISOR,
                objective="answer",
                observations=["hello"],
            )
        )

    assert decision.kind == DecisionKind.FINISH
    assert decision.final_output == "final answer"


@pytest.mark.asyncio
async def test_openai_compatible_client_maps_tool_call_response() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "rag_search",
                                        "arguments": "{\"kb_ids\": [\"kb-1\"], \"query\": \"hello\"}",
                                    }
                                }
                            ],
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        decision = await client.complete(
            ModelTurnInput(
                run_id="run-2",
                agent_id="agent-2",
                agent_role=AgentRole.SUPERVISOR,
                objective="search",
                observations=[],
            )
        )

    assert decision.kind == DecisionKind.CALL_TOOL
    assert decision.tool_name == "rag_search"
    assert decision.tool_arguments == {"kb_ids": ["kb-1"], "query": "hello"}


@pytest.mark.asyncio
async def test_openai_compatible_client_raises_runtime_error_on_bad_response() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "provider failed"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        with pytest.raises(RuntimeError, match="provider failed"):
            await client.complete(
                ModelTurnInput(
                    run_id="run-3",
                    agent_id="agent-3",
                    agent_role=AgentRole.SUPERVISOR,
                    objective="fail",
                    observations=[],
                )
            )
```

- [ ] **Step 2: Run provider tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_openai_compatible_model_client.py -v`
Expected: FAIL because `agent_runtime.models.openai_compatible` does not exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_openai_compatible_model_client.py
git commit -m "test: add compatible provider red coverage"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 3: Implement Assistant Persistence Tables, Records, And Repository

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\models.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\repository.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\tables.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\db.py`

- [ ] **Step 1: Extend persistence schema with assistant session, message, and run-link tables**

```python
class AssistantSessionTable(Base):
    __tablename__ = "assistant_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
```

- [ ] **Step 2: Add assistant-side record models**

```python
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_runtime.domain.models import utc_now


class AssistantSessionRecord(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    title: str
    mode: str
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AssistantMessageRecord(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    tenant_id: str
    role: str
    content: str
    structured_payload: dict[str, object] = Field(default_factory=dict)
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AssistantRunLinkRecord(BaseModel):
    link_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    message_id: str
    run_id: str
    launch_kind: str
    created_at: datetime = Field(default_factory=utc_now)
```

- [ ] **Step 3: Implement repository methods for assistant persistence**

```python
class AssistantRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_session(self, record: AssistantSessionRecord) -> AssistantSessionRecord: ...
    async def list_sessions(self, tenant_id: str) -> list[AssistantSessionRecord]: ...
    async def get_session(self, tenant_id: str, session_id: str) -> AssistantSessionRecord | None: ...
    async def add_message(self, record: AssistantMessageRecord) -> AssistantMessageRecord: ...
    async def list_messages(self, tenant_id: str, session_id: str) -> list[AssistantMessageRecord]: ...
    async def create_run_link(self, record: AssistantRunLinkRecord) -> AssistantRunLinkRecord: ...
    async def list_run_links(self, tenant_id: str, session_id: str) -> list[AssistantRunLinkRecord]: ...
```

- [ ] **Step 4: Run assistant service tests and confirm the persistence layer still leaves service tests failing at the service boundary**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_assistant_service.py -v`
Expected: FAIL, but now because `AssistantService` does not exist yet rather than because persistence modules are missing.

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/assistant/models.py src/agent_runtime/assistant/repository.py src/agent_runtime/state/tables.py src/agent_runtime/state/db.py
git commit -m "feat: add assistant persistence layer"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 4: Implement The OpenAI-Compatible Model Provider

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\models\openai_compatible.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\models\base.py` only if minimal abstraction support is necessary

- [ ] **Step 1: Implement minimal compatible-provider request and response mapping**

```python
from __future__ import annotations

import json

import httpx

from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput


class OpenAICompatibleModelClient(ModelClient):
    def __init__(self, *, http_client: httpx.AsyncClient, model_name: str) -> None:
        self._http_client = http_client
        self._model_name = model_name

    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        response = await self._http_client.post(
            "/chat/completions",
            json={
                "model": self._model_name,
                "messages": self._build_messages(turn),
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "rag_search",
                            "description": "Search tenant knowledge base",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "kb_ids": {"type": "array", "items": {"type": "string"}},
                                    "query": {"type": "string"},
                                    "top_k": {"type": "integer"},
                                    "include_compiled_context": {"type": "boolean"},
                                },
                                "required": ["kb_ids", "query"],
                            },
                        },
                    }
                ],
            },
        )
        if response.status_code >= 400:
            detail = response.json().get("error", {}).get("message", response.text)
            raise RuntimeError(detail)

        payload = response.json()
        choice = payload["choices"][0]["message"]
        tool_calls = choice.get("tool_calls") or []
        if tool_calls:
            function_payload = tool_calls[0]["function"]
            return ModelDecision(
                kind=DecisionKind.CALL_TOOL,
                summary=f"call tool {function_payload['name']}",
                tool_name=function_payload["name"],
                tool_arguments=json.loads(function_payload["arguments"]),
            )

        content = choice.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("compatible provider returned no assistant content")
        return ModelDecision(
            kind=DecisionKind.FINISH,
            summary="assistant replied",
            final_output=content,
        )

    @staticmethod
    def _build_messages(turn: ModelTurnInput) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": "You are an assistant running inside Agent Runtime. Use tools when needed.",
            }
        ]
        for observation in turn.observations:
            messages.append({"role": "user", "content": observation})
        messages.append({"role": "user", "content": turn.objective})
        return messages
```

- [ ] **Step 2: Run provider tests and verify they pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_openai_compatible_model_client.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/agent_runtime/models/openai_compatible.py tests/unit/test_openai_compatible_model_client.py
git commit -m "feat: add openai compatible model client"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 5: Implement Assistant Application Service

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\assistant\service.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_assistant_service.py`

- [ ] **Step 1: Implement assistant service entrypoints for session creation, chat, task, and activity**

```python
class AssistantService:
    def __init__(
        self,
        *,
        assistant_repository: AssistantRepository,
        run_service: RunService,
        workflow_service: WorkflowService | None = None,
        runtime_repository: RuntimeRepository | None = None,
    ) -> None:
        self._assistant_repository = assistant_repository
        self._run_service = run_service
        self._workflow_service = workflow_service
        self._runtime_repository = runtime_repository

    async def create_session(self, *, tenant_id: str, mode: str, title: str) -> AssistantSessionRecord: ...
    async def list_sessions(self, *, tenant_id: str) -> list[AssistantSessionRecord]: ...
    async def list_messages(self, *, tenant_id: str, session_id: str) -> list[AssistantMessageRecord]: ...
    async def send_chat_message(self, *, tenant_id: str, session_id: str, content: str) -> AssistantChatResult: ...
    async def create_task(
        self,
        *,
        tenant_id: str,
        session_id: str,
        objective: str,
        workflow_id: str | None = None,
        version: int | None = None,
        launch_input: dict[str, object] | None = None,
    ) -> AssistantTaskResult: ...
    async def get_activity(self, *, tenant_id: str, session_id: str) -> dict[str, object]: ...
```

- [ ] **Step 2: Make chat mode minimal but real for phase 1**

```python
async def send_chat_message(self, *, tenant_id: str, session_id: str, content: str) -> AssistantChatResult:
    session = await self._require_session(tenant_id=tenant_id, session_id=session_id)
    user_message = await self._assistant_repository.add_message(
        AssistantMessageRecord(
            session_id=session.session_id,
            tenant_id=tenant_id,
            role="user",
            content=content,
        )
    )

    run = await self._run_service.create_run(tenant_id=tenant_id, objective=content)
    await self._assistant_repository.create_run_link(
        AssistantRunLinkRecord(
            session_id=session.session_id,
            message_id=user_message.message_id,
            run_id=run.run_id,
            launch_kind="chat_turn",
        )
    )
    final_run = await self._run_service.resume_run(run.run_id)
    assistant_message = await self._assistant_repository.add_message(
        AssistantMessageRecord(
            session_id=session.session_id,
            tenant_id=tenant_id,
            role="assistant",
            content=final_run.result or final_run.error or "",
            run_id=run.run_id,
            structured_payload={"run_status": final_run.status.value},
        )
    )
    return AssistantChatResult(
        user_message=user_message,
        assistant_message=assistant_message,
        run_id=run.run_id,
        status=final_run.status.value,
    )
```

- [ ] **Step 3: Run assistant service tests and verify they pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_assistant_service.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agent_runtime/assistant/service.py tests/unit/test_assistant_service.py
git commit -m "feat: add assistant application service"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 6: Add Assistant API Schemas And Routes

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\assistant.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_assistant_api.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`

- [ ] **Step 1: Write failing assistant API integration tests**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context
from tests.integration.test_knowledge_bases_api import FakeEmbeddingProvider


@pytest.mark.asyncio
async def test_assistant_session_chat_and_activity_routes(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(kind="finish", summary="done", final_output="assistant hello")
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        session_response = await client.post(
            "/v1/assistant/sessions",
            json={"tenant_id": "tenant-a", "mode": "chat", "title": "Chat A"},
        )
        assert session_response.status_code == 201
        session_id = session_response.json()["session_id"]

        chat_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/chat",
            json={"tenant_id": "tenant-a", "content": "hello"},
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["assistant_message"]["content"] == "assistant hello"

        activity_response = await client.get(
            f"/v1/assistant/sessions/{session_id}/activity",
            params={"tenant_id": "tenant-a"},
        )
        assert activity_response.status_code == 200
        assert len(activity_response.json()["messages"]) == 2


@pytest.mark.asyncio
async def test_assistant_task_route_creates_linked_run(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(kind="finish", summary="done", final_output="task output")
                ]
            }
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        session_response = await client.post(
            "/v1/assistant/sessions",
            json={"tenant_id": "tenant-a", "mode": "task", "title": "Task A"},
        )
        session_id = session_response.json()["session_id"]

        task_response = await client.post(
            f"/v1/assistant/sessions/{session_id}/tasks",
            json={"tenant_id": "tenant-a", "objective": "Investigate incident"},
        )
        assert task_response.status_code == 201
        assert task_response.json()["run_id"] is not None
```

- [ ] **Step 2: Run assistant API tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_assistant_api.py -v`
Expected: FAIL with `404` because the assistant route family is not yet wired.

- [ ] **Step 3: Implement assistant request and response schemas**

```python
class AssistantSessionCreateRequest(BaseModel):
    tenant_id: str
    mode: str
    title: str


class AssistantSessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    title: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime


class AssistantChatRequest(BaseModel):
    tenant_id: str
    content: str


class AssistantMessageResponse(BaseModel):
    message_id: str
    session_id: str
    tenant_id: str
    role: str
    content: str
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    created_at: datetime
```

- [ ] **Step 4: Implement assistant routes and wire them in `create_app()`**

```python
router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


@router.post("/sessions", response_model=AssistantSessionResponse, status_code=201)
async def create_session(request: Request, payload: AssistantSessionCreateRequest) -> AssistantSessionResponse: ...


@router.get("/sessions", response_model=list[AssistantSessionResponse])
async def list_sessions(request: Request, tenant_id: str) -> list[AssistantSessionResponse]: ...


@router.get("/sessions/{session_id}/messages", response_model=list[AssistantMessageResponse])
async def list_messages(request: Request, session_id: str, tenant_id: str) -> list[AssistantMessageResponse]: ...


@router.post("/sessions/{session_id}/chat", response_model=AssistantChatResponse)
async def send_chat_message(request: Request, session_id: str, payload: AssistantChatRequest) -> AssistantChatResponse: ...


@router.post("/sessions/{session_id}/tasks", response_model=AssistantTaskResponse, status_code=201)
async def create_task(request: Request, session_id: str, payload: AssistantTaskRequest) -> AssistantTaskResponse: ...
```

- [ ] **Step 5: Run assistant API tests and verify they pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_assistant_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent_runtime/api/schemas.py src/agent_runtime/api/routes/assistant.py src/agent_runtime/api/app.py tests/integration/test_assistant_api.py
git commit -m "feat: add assistant api routes"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 7: Add Dedicated `/assistant` Workspace UI

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\assistant_ui.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\static\assistant\index.html`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\static\assistant\assistant.css`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\static\assistant\assistant.js`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_assistant_ui.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`

- [ ] **Step 1: Write failing assistant UI tests**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.api.app import create_app
from tests.conftest import app_client_context


@pytest.mark.asyncio
async def test_assistant_workspace_page_is_served(tmp_path: Path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        response = await client.get("/assistant")

    assert response.status_code == 200
    assert "Assistant Workspace" in response.text
    assert "/assistant/assets/assistant.js" in response.text


@pytest.mark.asyncio
async def test_assistant_workspace_assets_are_served(tmp_path: Path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        script_response = await client.get("/assistant/assets/assistant.js")
        stylesheet_response = await client.get("/assistant/assets/assistant.css")

    assert script_response.status_code == 200
    assert "loadSessions" in script_response.text
    assert stylesheet_response.status_code == 200
    assert ".workspace-shell" in stylesheet_response.text
```

- [ ] **Step 2: Run assistant UI tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_assistant_ui.py -v`
Expected: FAIL with `404` because `/assistant` is not mounted yet.

- [ ] **Step 3: Implement the dedicated assistant workspace**

```html
<div class="workspace-shell">
  <aside class="session-rail">...</aside>
  <main class="interaction-pane">...</main>
  <section class="context-pane">...</section>
</div>
```

```javascript
async function loadSessions() { ... }
async function createSession() { ... }
async function sendChat() { ... }
async function createTask() { ... }
async function loadActivity() { ... }
async function resolveApproval(action, approvalId) { ... }
```

- [ ] **Step 4: Mount `/assistant/assets` and serve `/assistant`**

```python
ASSISTANT_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "assistant"

app.mount("/assistant/assets", StaticFiles(directory=ASSISTANT_ASSETS_DIR), name="assistant-assets")
app.include_router(build_assistant_ui_router(ASSISTANT_ASSETS_DIR))
```

- [ ] **Step 5: Run assistant UI tests and verify they pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_assistant_ui.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent_runtime/api/routes/assistant_ui.py src/agent_runtime/api/static/assistant/index.html src/agent_runtime/api/static/assistant/assistant.css src/agent_runtime/api/static/assistant/assistant.js src/agent_runtime/api/app.py tests/integration/test_assistant_ui.py
git commit -m "feat: add assistant workspace ui"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 8: Wire Configurable Compatible Provider Into App Startup

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`

- [ ] **Step 1: Add environment-driven compatible provider bootstrap in `create_app()`**

```python
compatible_base_url = os.getenv("AGENT_RUNTIME_MODEL_BASE_URL")
compatible_api_key = os.getenv("AGENT_RUNTIME_MODEL_API_KEY")
compatible_model_name = os.getenv("AGENT_RUNTIME_MODEL_NAME")
compatible_timeout_seconds = float(os.getenv("AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS", "60"))

runtime_model_client = model_client
if runtime_model_client is None and compatible_base_url and compatible_model_name:
    headers = {}
    if compatible_api_key:
        headers["Authorization"] = f"Bearer {compatible_api_key}"
    http_client = httpx.AsyncClient(
        base_url=compatible_base_url.rstrip("/"),
        headers=headers,
        timeout=compatible_timeout_seconds,
    )
    runtime_model_client = OpenAICompatibleModelClient(
        http_client=http_client,
        model_name=compatible_model_name,
    )

if runtime_model_client is None:
    runtime_model_client = ScriptedModelClient({"supervisor": []})
```

- [ ] **Step 2: Ensure shutdown disposes the provider HTTP client if owned by the app**

```python
if getattr(app.state, "owned_model_http_client", None) is not None:
    await app.state.owned_model_http_client.aclose()
```

- [ ] **Step 3: Document assistant startup and compatible-provider environment variables**

```markdown
- `AGENT_RUNTIME_MODEL_BASE_URL`
- `AGENT_RUNTIME_MODEL_API_KEY`
- `AGENT_RUNTIME_MODEL_NAME`
- `AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS`

Open `/assistant` for the user-facing workspace and `/admin` for operator workflows.
```

- [ ] **Step 4: Run smoke and assistant regressions**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_app_smoke.py tests\integration\test_assistant_api.py tests\integration\test_assistant_ui.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api/app.py README.md docs/operations-runbook.md
git commit -m "feat: wire compatible model provider configuration"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 9: Validate Affected Runtime And Knowledge Paths Still Pass

**Files:**
- Modify only if regressions are found during verification.

- [ ] **Step 1: Run assistant-specific and affected existing regressions**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_openai_compatible_model_client.py tests\unit\test_assistant_service.py tests\integration\test_assistant_api.py tests\integration\test_assistant_ui.py tests\integration\test_app_smoke.py tests\integration\test_workflow_runs_api.py tests\integration\test_workflows_api.py tests\integration\test_knowledge_bases_api.py -v`
Expected: PASS

- [ ] **Step 2: Fix any regression using TDD before continuing**

```text
If any existing test fails, add or tighten the failing test around the real regression, rerun it to confirm RED, implement the minimal fix, and rerun the affected command until green.
```

- [ ] **Step 3: Commit only if regression fixes required code changes**

```bash
git add <affected-files>
git commit -m "fix: preserve runtime behavior after assistant integration"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 10: Add DeepSeek Manual Validation Path And Complete Final Verification

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\docs\assistant-deepseek-validation.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`

- [ ] **Step 1: Add a manual DeepSeek validation document**

```markdown
# Assistant DeepSeek Validation

## Required Environment

- `AGENT_RUNTIME_MODEL_BASE_URL`
- `AGENT_RUNTIME_MODEL_API_KEY`
- `AGENT_RUNTIME_MODEL_NAME=deepseek-chat`

## Validation Cases

1. Open `/assistant`
2. Create a chat session and send a normal message
3. Ask a knowledge question that triggers `rag_search`
4. Create a task-mode session and submit a task objective
5. Record:
   - response quality
   - linked run id
   - tool invocation behavior
   - any compatibility mismatch
```

- [ ] **Step 2: Run the full regression suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS

- [ ] **Step 3: Perform or schedule the manual DeepSeek validation**

```text
If credentials and endpoint are available during implementation, run the documented validation flow immediately and record the observed result in the validation doc.
If credentials are not available, leave the validation doc ready and explicitly note that live DeepSeek verification is the only remaining manual check.
```

- [ ] **Step 4: Commit documentation updates if changed**

```bash
git add docs/assistant-deepseek-validation.md README.md
git commit -m "docs: add deepseek assistant validation path"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

---

## Self-Review

### Spec Coverage

- compatible provider: covered by Tasks 2, 4, and 8
- assistant persistence: covered by Task 3
- assistant application layer: covered by Task 5
- assistant APIs: covered by Task 6
- `/assistant` workspace: covered by Task 7
- chat and task dual-mode behavior: covered by Tasks 5, 6, and 7
- DeepSeek validation target: covered by Task 10
- documentation and startup surface: covered by Task 8 and Task 10

No major spec gap remains.

### Placeholder Scan

- No `TBD`
- No `TODO`
- No unresolved “add validation” placeholders without a concrete target
- Verification commands are explicit

### Type Consistency

- assistant persistence types consistently use `AssistantSessionRecord`, `AssistantMessageRecord`, and `AssistantRunLinkRecord`
- assistant routes consistently use `/v1/assistant`
- user-facing workspace consistently uses `/assistant`
- compatible provider is consistently named `OpenAICompatibleModelClient`

No unresolved naming mismatch remains.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-assistant-phase1-openai-compatible-dual-mode.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
