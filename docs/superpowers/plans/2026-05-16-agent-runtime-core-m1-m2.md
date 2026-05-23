# Agent Runtime Core M1-M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first executable slice of the agent runtime core: a resilient FastAPI service with single-supervisor execution, durable events and checkpoints, resumable runs, and predefined supervisor-worker orchestration.

**Architecture:** The implementation uses an event-driven runtime with SQL-backed state, deterministic scripted model adapters for tests, and a scheduler that advances runs through explicit agent ticks. M1 delivers a single-agent resilient core; M2 extends the same primitives to supervisor-worker task dispatch and merge without introducing tools, approvals, or UI concerns.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite for local/test persistence, httpx, pytest, pytest-asyncio

---

## File Structure

### Create

- `pyproject.toml`
  Python package metadata, dependencies, pytest config.
- `src/agent_runtime/__init__.py`
  Package marker and version export.
- `src/agent_runtime/main.py`
  ASGI entrypoint for local execution.
- `src/agent_runtime/api/app.py`
  FastAPI app factory and startup database initialization.
- `src/agent_runtime/api/routes/runs.py`
  Run lifecycle and SSE event endpoints.
- `src/agent_runtime/api/schemas.py`
  Request and response DTOs for API handlers.
- `src/agent_runtime/domain/enums.py`
  Runtime statuses, roles, decision kinds, event types.
- `src/agent_runtime/domain/models.py`
  Pydantic domain models for runs, agents, tasks, checkpoints, events.
- `src/agent_runtime/models/base.py`
  Provider-agnostic `ModelClient` protocol and decision input/output schemas.
- `src/agent_runtime/models/scripted.py`
  Deterministic scripted provider used by tests and local development.
- `src/agent_runtime/state/db.py`
  Async engine, session factory, and schema initialization helpers.
- `src/agent_runtime/state/tables.py`
  SQLAlchemy ORM tables for runs, agents, tasks, events, checkpoints.
- `src/agent_runtime/state/repositories.py`
  Persistence layer for CRUD, event append, checkpoint lookup, and active-run scans.
- `src/agent_runtime/state/event_stream.py`
  In-process pub/sub hub for live SSE event fanout with persisted replay.
- `src/agent_runtime/runtime/orchestrator.py`
  Tick-driven runtime orchestration for supervisor and worker agents.
- `src/agent_runtime/runtime/services.py`
  Run service used by API handlers to create, start, query, resume, cancel, and stream runs.
- `src/agent_runtime/runtime/resume.py`
  Resume coordinator for explicit run resume and background restart scans.
- `src/agent_runtime/agents/profiles.py`
  Predefined worker profile names and validation helpers.
- `tests/conftest.py`
  Shared fixtures for temp SQLite databases, app factory, and test clients.
- `tests/integration/test_app_smoke.py`
  Basic app boot smoke test.
- `tests/unit/test_models_scripted_client.py`
  Unit tests for event construction and scripted model sequencing.
- `tests/integration/test_state_repositories.py`
  Repository round-trip tests for runs, events, and checkpoints.
- `tests/integration/test_run_lifecycle.py`
  End-to-end tests for create, start, complete, and event replay.
- `tests/integration/test_resume_flow.py`
  Resume tests using persisted checkpoints.
- `tests/integration/test_multi_agent_flow.py`
  End-to-end tests for supervisor-worker dispatch and merge.

### Modify Later in Plan

- `src/agent_runtime/api/app.py`
  Add runtime service wiring after persistence and orchestration exist.
- `src/agent_runtime/runtime/orchestrator.py`
  First implement single-agent flow, then extend to worker delegation.
- `src/agent_runtime/runtime/services.py`
  First implement create/start/query, then extend with resume and event streaming.

## Task 1: Bootstrap The Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/agent_runtime/__init__.py`
- Create: `src/agent_runtime/main.py`
- Create: `src/agent_runtime/api/app.py`
- Test: `tests/integration/test_app_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/integration/test_app_smoke.py
import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app


@pytest.mark.asyncio
async def test_healthcheck_returns_ok() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `pytest tests/integration/test_app_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_runtime'`

- [ ] **Step 3: Write the minimal package and FastAPI app**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "agent-runtime"
version = "0.1.0"
description = "Event-driven multi-agent runtime core"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.115.0,<1.0.0",
  "uvicorn>=0.30.0,<1.0.0",
  "pydantic>=2.8.0,<3.0.0",
  "sqlalchemy>=2.0.36,<3.0.0",
  "aiosqlite>=0.20.0,<1.0.0",
  "httpx>=0.27.0,<1.0.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0,<9.0.0",
  "pytest-asyncio>=0.24.0,<1.0.0",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
testpaths = ["tests"]
```

```python
# src/agent_runtime/__init__.py
__all__ = ["__version__"]

__version__ = "0.1.0"
```

```python
# src/agent_runtime/api/app.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Runtime", version="0.1.0")

    @app.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

```python
# src/agent_runtime/main.py
from agent_runtime.api.app import create_app

app = create_app()
```

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `pytest tests/integration/test_app_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/agent_runtime tests/integration/test_app_smoke.py
git commit -m "chore: bootstrap agent runtime service"
```

## Task 2: Define Core Domain Models And Scripted Model Contract

**Files:**
- Create: `src/agent_runtime/domain/enums.py`
- Create: `src/agent_runtime/domain/models.py`
- Create: `src/agent_runtime/models/base.py`
- Create: `src/agent_runtime/models/scripted.py`
- Test: `tests/unit/test_models_scripted_client.py`

- [ ] **Step 1: Write failing unit tests for events and scripted decisions**

```python
# tests/unit/test_models_scripted_client.py
import pytest

from agent_runtime.domain.enums import AgentRole, DecisionKind, EventType
from agent_runtime.domain.models import RuntimeEvent
from agent_runtime.models.base import ModelDecision, ModelTurnInput
from agent_runtime.models.scripted import ScriptedModelClient


def test_runtime_event_builds_with_expected_fields() -> None:
    event = RuntimeEvent.build(
        tenant_id="tenant-a",
        run_id="run-1",
        event_type=EventType.RUN_CREATED,
        payload={"objective": "summarize"},
    )

    assert event.tenant_id == "tenant-a"
    assert event.run_id == "run-1"
    assert event.event_type == EventType.RUN_CREATED
    assert event.payload == {"objective": "summarize"}
    assert event.event_id


@pytest.mark.asyncio
async def test_scripted_model_client_returns_role_specific_decisions_in_order() -> None:
    client = ScriptedModelClient(
        {
            "supervisor": [
                ModelDecision(kind=DecisionKind.DELEGATE, summary="delegate", worker_role=AgentRole.RESEARCHER, task_input="gather facts"),
                ModelDecision(kind=DecisionKind.FINISH, summary="finish", final_output="done"),
            ]
        }
    )

    turn = ModelTurnInput(
        run_id="run-1",
        agent_id="agent-1",
        agent_role=AgentRole.SUPERVISOR,
        objective="handle request",
        observations=[],
    )

    first = await client.complete(turn)
    second = await client.complete(turn)

    assert first.kind == DecisionKind.DELEGATE
    assert first.worker_role == AgentRole.RESEARCHER
    assert second.kind == DecisionKind.FINISH
    assert second.final_output == "done"
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `pytest tests/unit/test_models_scripted_client.py -v`
Expected: FAIL with import errors for missing domain and model modules

- [ ] **Step 3: Implement enums, domain models, and scripted model adapter**

```python
# src/agent_runtime/domain/enums.py
from enum import StrEnum


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    REASONING = "reasoning"
    WAITING_ON_WORKERS = "waiting_on_workers"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    TOOL_RUNNER = "tool-runner"


class DecisionKind(StrEnum):
    FINISH = "finish"
    DELEGATE = "delegate"


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    AGENT_STARTED = "agent.started"
    AGENT_REASONED = "agent.reasoned"
    AGENT_COMPLETED = "agent.completed"
    TASK_DISPATCHED = "task.dispatched"
    CHECKPOINT_CREATED = "checkpoint.created"
```

```python
# src/agent_runtime/domain/models.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_runtime.domain.enums import AgentRole, AgentStatus, EventType, RunStatus, TaskStatus


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
```

```python
# src/agent_runtime/models/base.py
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from agent_runtime.domain.enums import AgentRole, DecisionKind


class ModelTurnInput(BaseModel):
    run_id: str
    agent_id: str
    agent_role: AgentRole
    objective: str
    observations: list[str] = Field(default_factory=list)


class ModelDecision(BaseModel):
    kind: DecisionKind
    summary: str
    final_output: str | None = None
    worker_role: AgentRole | None = None
    task_input: str | None = None


class ModelClient(Protocol):
    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        ...
```

```python
# src/agent_runtime/models/scripted.py
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput


class ScriptedModelClient(ModelClient):
    def __init__(self, scripts: Mapping[str, Sequence[ModelDecision]]) -> None:
        self._scripts = {role: list(decisions) for role, decisions in scripts.items()}
        self._offsets: dict[str, int] = defaultdict(int)

    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        role_key = turn.agent_role.value
        decisions = self._scripts.get(role_key, [])
        index = self._offsets[role_key]

        if index >= len(decisions):
            raise RuntimeError(f"no scripted decision remaining for role={role_key}")

        self._offsets[role_key] += 1
        return decisions[index]
```

- [ ] **Step 4: Run the new unit tests**

Run: `pytest tests/unit/test_models_scripted_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/domain src/agent_runtime/models tests/unit/test_models_scripted_client.py
git commit -m "feat: add runtime domain models and scripted model client"
```

## Task 3: Add SQLite Persistence For Runs, Events, Tasks, And Checkpoints

**Files:**
- Create: `src/agent_runtime/state/db.py`
- Create: `src/agent_runtime/state/tables.py`
- Create: `src/agent_runtime/state/repositories.py`
- Test: `tests/integration/test_state_repositories.py`

- [ ] **Step 1: Write the failing repository round-trip test**

```python
# tests/integration/test_state_repositories.py
import pytest

from agent_runtime.domain.enums import AgentRole, EventType
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RunRecord, RuntimeEvent
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_repository_persists_run_event_and_checkpoint(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)

    run = RunRecord(tenant_id="tenant-a", objective="summarize")
    supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=run.objective)
    await repository.create_run(run, supervisor)

    event = RuntimeEvent.build(
        tenant_id=run.tenant_id,
        run_id=run.run_id,
        event_type=EventType.RUN_CREATED,
        payload={"objective": run.objective},
        agent_id=supervisor.agent_id,
    )
    await repository.append_event(event)

    checkpoint = CheckpointRecord(
        run_id=run.run_id,
        agent_id=supervisor.agent_id,
        step_name="before_model",
        payload={"observations": []},
    )
    await repository.save_checkpoint(checkpoint)

    stored_run = await repository.get_run(run.run_id)
    stored_events = await repository.list_events(run.run_id)
    latest_checkpoint = await repository.get_latest_checkpoint(run.run_id, supervisor.agent_id)

    assert stored_run is not None
    assert stored_run.run_id == run.run_id
    assert len(stored_events) == 1
    assert stored_events[0].event_type == EventType.RUN_CREATED
    assert latest_checkpoint is not None
    assert latest_checkpoint.step_name == "before_model"
```

- [ ] **Step 2: Run the repository test to verify it fails**

Run: `pytest tests/integration/test_state_repositories.py -v`
Expected: FAIL with import errors for missing state modules

- [ ] **Step 3: Implement the database layer and repository**

```python
# src/agent_runtime/state/db.py
from collections.abc import AsyncIterator, Callable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from agent_runtime.state.tables import Base

SessionFactory = Callable[[], AsyncIterator[AsyncSession]]


def build_engine(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url, future=True)


def build_session_factory(db_url: str) -> async_sessionmaker[AsyncSession]:
    engine = build_engine(db_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        async with session.bind.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
```

```python
# src/agent_runtime/state/tables.py
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentTable(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    objective: Mapped[str] = mapped_column(Text())
    observations: Mapped[list[str]] = mapped_column(JSON)
    parent_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskTable(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_agent_id: Mapped[str] = mapped_column(String(64), index=True)
    worker_agent_id: Mapped[str] = mapped_column(String(64), index=True)
    worker_role: Mapped[str] = mapped_column(String(32))
    objective: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventTable(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CheckpointTable(Base):
    __tablename__ = "checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    step_name: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

```python
# src/agent_runtime/state/repositories.py
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.domain.enums import AgentRole, AgentStatus, EventType, RunStatus, TaskStatus
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RunRecord, RuntimeEvent, TaskRecord
from agent_runtime.state.tables import AgentTable, CheckpointTable, EventTable, RunTable, TaskTable


def utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run(self, run: RunRecord, supervisor: AgentRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                RunTable(
                    run_id=run.run_id,
                    tenant_id=run.tenant_id,
                    objective=run.objective,
                    status=run.status.value,
                    result=run.result,
                    error=run.error,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            session.add(
                AgentTable(
                    agent_id=supervisor.agent_id,
                    run_id=supervisor.run_id,
                    role=supervisor.role.value,
                    status=supervisor.status.value,
                    objective=supervisor.objective,
                    observations=supervisor.observations,
                    parent_agent_id=supervisor.parent_agent_id,
                    task_id=supervisor.task_id,
                    created_at=supervisor.created_at,
                    updated_at=supervisor.updated_at,
                )
            )
            await session.commit()

    async def append_event(self, event: RuntimeEvent) -> None:
        async with self._session_factory() as session:
            session.add(
                EventTable(
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    run_id=event.run_id,
                    agent_id=event.agent_id,
                    event_type=event.event_type.value,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )
            await session.commit()

    async def save_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                CheckpointTable(
                    checkpoint_id=checkpoint.checkpoint_id,
                    run_id=checkpoint.run_id,
                    agent_id=checkpoint.agent_id,
                    step_name=checkpoint.step_name,
                    payload=checkpoint.payload,
                    created_at=checkpoint.created_at,
                )
            )
            await session.commit()

    async def add_agent(self, agent: AgentRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                AgentTable(
                    agent_id=agent.agent_id,
                    run_id=agent.run_id,
                    role=agent.role.value,
                    status=agent.status.value,
                    objective=agent.objective,
                    observations=agent.observations,
                    parent_agent_id=agent.parent_agent_id,
                    task_id=agent.task_id,
                    created_at=agent.created_at,
                    updated_at=agent.updated_at,
                )
            )
            await session.commit()

    async def add_task(self, task: TaskRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                TaskTable(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    parent_agent_id=task.parent_agent_id,
                    worker_agent_id=task.worker_agent_id,
                    worker_role=task.worker_role.value,
                    objective=task.objective,
                    status=task.status.value,
                    result=task.result,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )
            await session.commit()

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._session_factory() as session:
            row = await session.get(RunTable, run_id)
            if row is None:
                return None
            return RunRecord.model_validate(row.__dict__)

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        async with self._session_factory() as session:
            row = await session.get(AgentTable, agent_id)
            if row is None:
                return None
            data = {
                "agent_id": row.agent_id,
                "run_id": row.run_id,
                "role": AgentRole(row.role),
                "status": AgentStatus(row.status),
                "objective": row.objective,
                "observations": row.observations,
                "parent_agent_id": row.parent_agent_id,
                "task_id": row.task_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            return AgentRecord.model_validate(data)

    async def list_agents(self, run_id: str) -> list[AgentRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(select(AgentTable).where(AgentTable.run_id == run_id).order_by(AgentTable.created_at))
            ).scalars()
            return [
                AgentRecord(
                    agent_id=row.agent_id,
                    run_id=row.run_id,
                    role=AgentRole(row.role),
                    status=AgentStatus(row.status),
                    objective=row.objective,
                    observations=row.observations,
                    parent_agent_id=row.parent_agent_id,
                    task_id=row.task_id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def list_events(self, run_id: str) -> list[RuntimeEvent]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(select(EventTable).where(EventTable.run_id == run_id).order_by(EventTable.created_at))
            ).scalars()
            return [
                RuntimeEvent(
                    event_id=row.event_id,
                    tenant_id=row.tenant_id,
                    run_id=row.run_id,
                    event_type=EventType(row.event_type),
                    payload=row.payload,
                    agent_id=row.agent_id,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    async def list_tasks(self, run_id: str) -> list[TaskRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(select(TaskTable).where(TaskTable.run_id == run_id).order_by(TaskTable.created_at))
            ).scalars()
            return [
                TaskRecord(
                    task_id=row.task_id,
                    run_id=row.run_id,
                    parent_agent_id=row.parent_agent_id,
                    worker_agent_id=row.worker_agent_id,
                    worker_role=AgentRole(row.worker_role),
                    objective=row.objective,
                    status=TaskStatus(row.status),
                    result=row.result,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def get_latest_checkpoint(self, run_id: str, agent_id: str) -> CheckpointRecord | None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(CheckpointTable)
                    .where(CheckpointTable.run_id == run_id, CheckpointTable.agent_id == agent_id)
                    .order_by(CheckpointTable.created_at.desc())
                    .limit(1)
                )
            ).scalars().all()
            if not rows:
                return None
            row = rows[0]
            return CheckpointRecord(
                checkpoint_id=row.checkpoint_id,
                run_id=row.run_id,
                agent_id=row.agent_id,
                step_name=row.step_name,
                payload=row.payload,
                created_at=row.created_at,
            )

    async def update_run_status(self, run_id: str, status: RunStatus, *, result: str | None = None, error: str | None = None) -> None:
        async with self._session_factory() as session:
            row = await session.get(RunTable, run_id)
            if row is None:
                raise RuntimeError(f"run not found: {run_id}")
            row.status = status.value
            row.result = result
            row.error = error
            row.updated_at = utc_now()
            await session.commit()

    async def update_agent_state(
        self,
        agent_id: str,
        *,
        status: AgentStatus | None = None,
        observations: list[str] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(AgentTable, agent_id)
            if row is None:
                raise RuntimeError(f"agent not found: {agent_id}")
            if status is not None:
                row.status = status.value
            if observations is not None:
                row.observations = observations
            row.updated_at = utc_now()
            await session.commit()

    async def update_task_state(self, task_id: str, *, status: TaskStatus, result: str | None = None) -> None:
        async with self._session_factory() as session:
            row = await session.get(TaskTable, task_id)
            if row is None:
                raise RuntimeError(f"task not found: {task_id}")
            row.status = status.value
            row.result = result
            row.updated_at = utc_now()
            await session.commit()

    async def list_active_runs(self) -> list[RunRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(RunTable).where(RunTable.status.in_([RunStatus.CREATED.value, RunStatus.RUNNING.value, RunStatus.PAUSED.value]))
                )
            ).scalars()
            return [
                RunRecord(
                    run_id=row.run_id,
                    tenant_id=row.tenant_id,
                    objective=row.objective,
                    status=RunStatus(row.status),
                    result=row.result,
                    error=row.error,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]
```

- [ ] **Step 4: Run the repository test**

Run: `pytest tests/integration/test_state_repositories.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/state tests/integration/test_state_repositories.py
git commit -m "feat: add sqlite-backed runtime repository"
```

## Task 4: Implement Single-Agent Execution And Run APIs

**Files:**
- Create: `src/agent_runtime/state/event_stream.py`
- Create: `src/agent_runtime/runtime/orchestrator.py`
- Create: `src/agent_runtime/runtime/services.py`
- Create: `src/agent_runtime/api/schemas.py`
- Create: `src/agent_runtime/api/routes/runs.py`
- Modify: `src/agent_runtime/api/app.py`
- Modify: `src/agent_runtime/main.py`
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_run_lifecycle.py`

- [ ] **Step 1: Write the failing end-to-end run lifecycle test**

```python
# tests/integration/test_run_lifecycle.py
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient


@pytest.mark.asyncio
async def test_create_run_completes_and_replays_events(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="final answer")
                ]
            }
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "summarize incident"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        assert payload["status"] == "completed"
        assert payload["result"] == "final answer"

        events_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        assert events_response.status_code == 200
        event_types = [item["event_type"] for item in events_response.json()["events"]]
        assert event_types[0] == "run.created"
        assert event_types[-1] == "run.completed"
```

- [ ] **Step 2: Run the lifecycle test to verify it fails**

Run: `pytest tests/integration/test_run_lifecycle.py -v`
Expected: FAIL with `TypeError` because `create_app()` does not yet accept dependencies or routes

- [ ] **Step 3: Implement event fanout, orchestrator, run service, and API routes**

```python
# src/agent_runtime/state/event_stream.py
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from agent_runtime.domain.models import RuntimeEvent


class EventStreamHub:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[RuntimeEvent]]] = defaultdict(list)

    async def publish(self, event: RuntimeEvent) -> None:
        for queue in list(self._queues.get(event.run_id, [])):
            await queue.put(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._queues[run_id].append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[run_id].remove(queue)
```

```python
# src/agent_runtime/runtime/orchestrator.py
from __future__ import annotations

from agent_runtime.domain.enums import AgentStatus, EventType, RunStatus
from agent_runtime.domain.models import CheckpointRecord, RuntimeEvent
from agent_runtime.models.base import ModelClient, ModelTurnInput
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


class RuntimeOrchestrator:
    def __init__(self, repository: RuntimeRepository, model_client: ModelClient, event_hub: EventStreamHub) -> None:
        self._repository = repository
        self._model_client = model_client
        self._event_hub = event_hub

    async def execute_run(self, run_id: str) -> None:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")

        supervisor = (await self._repository.list_agents(run_id))[0]
        await self._repository.update_run_status(run_id, RunStatus.RUNNING)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_STARTED,
                payload={"objective": run.objective},
            )
        )
        await self._repository.update_agent_state(supervisor.agent_id, status=AgentStatus.REASONING)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.AGENT_STARTED,
                payload={"role": supervisor.role.value},
            )
        )
        checkpoint = CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": supervisor.observations},
        )
        await self._repository.save_checkpoint(checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": checkpoint.step_name},
            )
        )

        decision = await self._model_client.complete(
            ModelTurnInput(
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                agent_role=supervisor.role,
                objective=supervisor.objective,
                observations=supervisor.observations,
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.AGENT_REASONED,
                payload=decision.model_dump(mode="json"),
            )
        )
        await self._repository.update_agent_state(supervisor.agent_id, status=AgentStatus.COMPLETED)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.AGENT_COMPLETED,
                payload={"final_output": decision.final_output},
            )
        )
        await self._repository.update_run_status(run.run_id, RunStatus.COMPLETED, result=decision.final_output)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                event_type=EventType.RUN_COMPLETED,
                payload={"result": decision.final_output},
            )
        )

    async def _emit(self, event: RuntimeEvent) -> None:
        await self._repository.append_event(event)
        await self._event_hub.publish(event)
```

```python
# src/agent_runtime/runtime/services.py
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from agent_runtime.domain.enums import AgentRole, EventType, RunStatus
from agent_runtime.domain.models import AgentRecord, RunRecord, RuntimeEvent
from agent_runtime.models.base import ModelClient
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator


class RunService:
    def __init__(self, repository: RuntimeRepository, model_client: ModelClient, event_hub: EventStreamHub) -> None:
        self._repository = repository
        self._model_client = model_client
        self._event_hub = event_hub
        self._orchestrator = RuntimeOrchestrator(repository, model_client, event_hub)

    async def create_run(self, tenant_id: str, objective: str) -> RunRecord:
        run = RunRecord(tenant_id=tenant_id, objective=objective)
        supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=objective)
        await self._repository.create_run(run, supervisor)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_CREATED,
                payload={"objective": objective},
            )
        )
        asyncio.create_task(self._orchestrator.execute_run(run.run_id))
        return run

    async def get_run(self, run_id: str) -> RunRecord:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        return run

    async def cancel_run(self, run_id: str) -> None:
        run = await self.get_run(run_id)
        await self._repository.update_run_status(run_id, RunStatus.CANCELLED)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run_id,
                event_type=EventType.RUN_CANCELLED,
                payload={"reason": "cancelled by api"},
            )
        )

    async def replay_events(self, run_id: str) -> list[RuntimeEvent]:
        return await self._repository.list_events(run_id)

    async def stream_events(self, run_id: str) -> AsyncIterator[str]:
        persisted = await self._repository.list_events(run_id)
        for event in persisted:
            yield f"data: {event.model_dump_json()}\n\n"
        async for event in self._event_hub.subscribe(run_id):
            yield f"data: {event.model_dump_json()}\n\n"
```

```python
# src/agent_runtime/api/schemas.py
from pydantic import BaseModel


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


class EventReplayResponse(BaseModel):
    events: list[dict]
```

```python
# src/agent_runtime/api/routes/runs.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent_runtime.api.schemas import CreateRunRequest, EventReplayResponse, RunResponse

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(request: Request, payload: CreateRunRequest) -> RunResponse:
    run = await request.app.state.run_service.create_run(payload.tenant_id, payload.objective)
    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(request: Request, run_id: str) -> RunResponse:
    try:
        run = await request.app.state.run_service.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(request: Request, run_id: str) -> dict[str, str]:
    await request.app.state.run_service.cancel_run(run_id)
    return {"status": "accepted"}


@router.get("/{run_id}/events")
async def stream_events(request: Request, run_id: str) -> StreamingResponse:
    return StreamingResponse(
        request.app.state.run_service.stream_events(run_id),
        media_type="text/event-stream",
    )


@router.get("/{run_id}/events/replay", response_model=EventReplayResponse)
async def replay_events(request: Request, run_id: str) -> EventReplayResponse:
    events = await request.app.state.run_service.replay_events(run_id)
    return EventReplayResponse(events=[event.model_dump(mode="json") for event in events])
```

```python
# src/agent_runtime/api/app.py
from fastapi import FastAPI

from agent_runtime.api.routes.runs import router as runs_router
from agent_runtime.models.base import ModelClient
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.runtime.services import RunService


def create_app(
    *,
    db_url: str = "sqlite+aiosqlite:///./runtime.db",
    model_client: ModelClient | None = None,
) -> FastAPI:
    app = FastAPI(title="Agent Runtime", version="0.1.0")

    session_factory = build_session_factory(db_url)
    repository = RuntimeRepository(session_factory)
    event_hub = EventStreamHub()
    app.state.run_service = RunService(
        repository,
        model_client or ScriptedModelClient({"supervisor": []}),
        event_hub,
    )

    @app.on_event("startup")
    async def startup() -> None:
        await init_db(session_factory)

    @app.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(runs_router)
    return app
```

```python
# src/agent_runtime/main.py
from agent_runtime.api.app import create_app

app = create_app()
```

- [ ] **Step 4: Run the app smoke and lifecycle tests**

Run: `pytest tests/integration/test_app_smoke.py tests/integration/test_run_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api src/agent_runtime/runtime src/agent_runtime/state/event_stream.py tests/integration/test_run_lifecycle.py
git commit -m "feat: add single-agent run lifecycle and event replay api"
```

## Task 5: Add Checkpoint-Based Resume Coordination

**Files:**
- Create: `src/agent_runtime/runtime/resume.py`
- Modify: `src/agent_runtime/runtime/orchestrator.py`
- Modify: `src/agent_runtime/runtime/services.py`
- Test: `tests/integration/test_resume_flow.py`

- [ ] **Step 1: Write the failing resume test**

```python
# tests/integration/test_resume_flow.py
import pytest

from agent_runtime.domain.enums import AgentRole, AgentStatus, DecisionKind, RunStatus
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RunRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.runtime.resume import ResumeCoordinator
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_resume_coordinator_continues_from_latest_checkpoint(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)
    event_hub = EventStreamHub()

    run = RunRecord(tenant_id="tenant-a", objective="recover this run", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.REASONING,
    )
    await repository.create_run(run, supervisor)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": ["checkpoint recovered"]},
        )
    )

    orchestrator = RuntimeOrchestrator(
        repository=repository,
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(kind=DecisionKind.FINISH, summary="recovered", final_output="resume complete")
                ]
            }
        ),
        event_hub=event_hub,
    )
    coordinator = ResumeCoordinator(repository, orchestrator)

    await coordinator.resume_run(run.run_id)

    stored_run = await repository.get_run(run.run_id)
    latest_checkpoint = await repository.get_latest_checkpoint(run.run_id, supervisor.agent_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.COMPLETED
    assert stored_run.result == "resume complete"
    assert latest_checkpoint is not None
    assert latest_checkpoint.step_name == "completed"
```

- [ ] **Step 2: Run the resume test to verify it fails**

Run: `pytest tests/integration/test_resume_flow.py -v`
Expected: FAIL with import errors for missing `ResumeCoordinator` and incomplete checkpoint behavior

- [ ] **Step 3: Implement resume coordination and post-completion checkpoints**

```python
# src/agent_runtime/runtime/resume.py
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.state.repositories import RuntimeRepository


class ResumeCoordinator:
    def __init__(self, repository: RuntimeRepository, orchestrator: RuntimeOrchestrator) -> None:
        self._repository = repository
        self._orchestrator = orchestrator

    async def resume_run(self, run_id: str) -> None:
        await self._orchestrator.execute_run(run_id)

    async def resume_active_runs(self) -> None:
        for run in await self._repository.list_active_runs():
            await self._orchestrator.execute_run(run.run_id)
```

```python
# src/agent_runtime/runtime/orchestrator.py
from __future__ import annotations

from agent_runtime.domain.enums import AgentStatus, EventType, RunStatus
from agent_runtime.domain.models import CheckpointRecord, RuntimeEvent
from agent_runtime.models.base import ModelClient, ModelTurnInput
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


class RuntimeOrchestrator:
    def __init__(self, repository: RuntimeRepository, model_client: ModelClient, event_hub: EventStreamHub) -> None:
        self._repository = repository
        self._model_client = model_client
        self._event_hub = event_hub

    async def execute_run(self, run_id: str) -> None:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")

        supervisor = (await self._repository.list_agents(run_id))[0]
        latest_checkpoint = await self._repository.get_latest_checkpoint(run_id, supervisor.agent_id)
        restored_observations = supervisor.observations
        if latest_checkpoint is not None:
            restored_observations = list(latest_checkpoint.payload.get("observations", supervisor.observations))

        await self._repository.update_run_status(run_id, RunStatus.RUNNING)
        await self._repository.update_agent_state(
            supervisor.agent_id,
            status=AgentStatus.REASONING,
            observations=restored_observations,
        )

        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_STARTED,
                payload={"objective": run.objective, "resumed": latest_checkpoint is not None},
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.AGENT_STARTED,
                payload={"role": supervisor.role.value},
            )
        )

        before_model = CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": restored_observations},
        )
        await self._repository.save_checkpoint(before_model)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": "before_model"},
            )
        )

        decision = await self._model_client.complete(
            ModelTurnInput(
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                agent_role=supervisor.role,
                objective=supervisor.objective,
                observations=restored_observations,
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.AGENT_REASONED,
                payload=decision.model_dump(mode="json"),
            )
        )
        await self._repository.update_agent_state(supervisor.agent_id, status=AgentStatus.COMPLETED)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.AGENT_COMPLETED,
                payload={"final_output": decision.final_output},
            )
        )
        await self._repository.update_run_status(run.run_id, RunStatus.COMPLETED, result=decision.final_output)
        completed_checkpoint = CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="completed",
            payload={"result": decision.final_output, "observations": restored_observations},
        )
        await self._repository.save_checkpoint(completed_checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": "completed"},
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                event_type=EventType.RUN_COMPLETED,
                payload={"result": decision.final_output},
            )
        )
```

```python
# src/agent_runtime/runtime/services.py
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from agent_runtime.domain.enums import AgentRole, EventType, RunStatus
from agent_runtime.domain.models import AgentRecord, RunRecord, RuntimeEvent
from agent_runtime.models.base import ModelClient
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.runtime.resume import ResumeCoordinator


class RunService:
    def __init__(self, repository: RuntimeRepository, model_client: ModelClient, event_hub: EventStreamHub) -> None:
        self._repository = repository
        self._event_hub = event_hub
        self._orchestrator = RuntimeOrchestrator(repository, model_client, event_hub)
        self._resume = ResumeCoordinator(repository, self._orchestrator)

    async def create_run(self, tenant_id: str, objective: str) -> RunRecord:
        run = RunRecord(tenant_id=tenant_id, objective=objective)
        supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=objective)
        await self._repository.create_run(run, supervisor)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_CREATED,
                payload={"objective": objective},
            )
        )
        asyncio.create_task(self._orchestrator.execute_run(run.run_id))
        return run

    async def get_run(self, run_id: str) -> RunRecord:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        return run

    async def resume_run(self, run_id: str) -> RunRecord:
        await self._resume.resume_run(run_id)
        return await self.get_run(run_id)

    async def cancel_run(self, run_id: str) -> None:
        run = await self.get_run(run_id)
        await self._repository.update_run_status(run_id, RunStatus.CANCELLED)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run_id,
                event_type=EventType.RUN_CANCELLED,
                payload={"reason": "cancelled by api"},
            )
        )

    async def replay_events(self, run_id: str) -> list[RuntimeEvent]:
        return await self._repository.list_events(run_id)

    async def stream_events(self, run_id: str) -> AsyncIterator[str]:
        persisted = await self._repository.list_events(run_id)
        for event in persisted:
            yield f"data: {event.model_dump_json()}\n\n"
        async for event in self._event_hub.subscribe(run_id):
            yield f"data: {event.model_dump_json()}\n\n"
```

- [ ] **Step 4: Run the lifecycle and resume tests**

Run: `pytest tests/integration/test_run_lifecycle.py tests/integration/test_resume_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/runtime tests/integration/test_resume_flow.py
git commit -m "feat: add checkpoint-based run resume"
```

## Task 6: Extend The Orchestrator To Supervisor-Worker Delegation

**Files:**
- Create: `src/agent_runtime/agents/profiles.py`
- Modify: `src/agent_runtime/runtime/orchestrator.py`
- Modify: `src/agent_runtime/runtime/services.py`
- Test: `tests/integration/test_multi_agent_flow.py`

- [ ] **Step 1: Write the failing multi-agent orchestration test**

```python
# tests/integration/test_multi_agent_flow.py
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import AgentRole, DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient


@pytest.mark.asyncio
async def test_supervisor_dispatches_worker_and_merges_result(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.DELEGATE,
                        summary="delegate research",
                        worker_role=AgentRole.RESEARCHER,
                        task_input="collect incident facts",
                    ),
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="finish with worker evidence",
                        final_output="incident summary with worker evidence",
                    ),
                ],
                "researcher": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="worker complete",
                        final_output="facts collected",
                    )
                ],
            }
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "investigate alert"},
        )
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        event_types = [event["event_type"] for event in replay_response.json()["events"]]

        assert payload["status"] == "completed"
        assert payload["result"] == "incident summary with worker evidence"
        assert "task.dispatched" in event_types
        assert event_types.count("agent.completed") == 2
```

- [ ] **Step 2: Run the multi-agent test to verify it fails**

Run: `pytest tests/integration/test_multi_agent_flow.py -v`
Expected: FAIL because the orchestrator handles only single-agent completion

- [ ] **Step 3: Implement worker profiles and delegation flow**

```python
# src/agent_runtime/agents/profiles.py
from agent_runtime.domain.enums import AgentRole

PREDEFINED_WORKER_ROLES = {AgentRole.RESEARCHER, AgentRole.TOOL_RUNNER}


def ensure_predefined_worker(role: AgentRole) -> AgentRole:
    if role not in PREDEFINED_WORKER_ROLES:
        raise RuntimeError(f"unsupported worker role: {role}")
    return role
```

```python
# src/agent_runtime/runtime/orchestrator.py
from __future__ import annotations

from agent_runtime.agents.profiles import ensure_predefined_worker
from agent_runtime.domain.enums import AgentRole, AgentStatus, DecisionKind, EventType, RunStatus, TaskStatus
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RuntimeEvent, TaskRecord
from agent_runtime.models.base import ModelClient, ModelTurnInput
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


class RuntimeOrchestrator:
    def __init__(self, repository: RuntimeRepository, model_client: ModelClient, event_hub: EventStreamHub) -> None:
        self._repository = repository
        self._model_client = model_client
        self._event_hub = event_hub

    async def execute_run(self, run_id: str) -> None:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        supervisor = (await self._repository.list_agents(run_id))[0]
        await self._run_agent(run.tenant_id, supervisor.agent_id)

    async def _run_agent(self, tenant_id: str, agent_id: str) -> str:
        agent = await self._repository.get_agent(agent_id)
        if agent is None:
            raise RuntimeError(f"agent not found: {agent_id}")

        await self._repository.update_agent_state(agent.agent_id, status=AgentStatus.REASONING)
        checkpoint = CheckpointRecord(
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            step_name="before_model",
            payload={"observations": agent.observations},
        )
        await self._repository.save_checkpoint(checkpoint)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.CHECKPOINT_CREATED,
                payload={"step_name": "before_model"},
            )
        )
        decision = await self._model_client.complete(
            ModelTurnInput(
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                agent_role=agent.role,
                objective=agent.objective,
                observations=agent.observations,
            )
        )
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.AGENT_REASONED,
                payload=decision.model_dump(mode="json"),
            )
        )

        if decision.kind == DecisionKind.FINISH:
            await self._repository.update_agent_state(agent.agent_id, status=AgentStatus.COMPLETED)
            await self._repository.save_checkpoint(
                CheckpointRecord(
                    run_id=agent.run_id,
                    agent_id=agent.agent_id,
                    step_name="completed",
                    payload={"result": decision.final_output, "observations": agent.observations},
                )
            )
            await self._emit(
                RuntimeEvent.build(
                    tenant_id=tenant_id,
                    run_id=agent.run_id,
                    agent_id=agent.agent_id,
                    event_type=EventType.AGENT_COMPLETED,
                    payload={"final_output": decision.final_output},
                )
            )
            if agent.role == AgentRole.SUPERVISOR:
                await self._repository.update_run_status(agent.run_id, RunStatus.COMPLETED, result=decision.final_output)
                await self._emit(
                    RuntimeEvent.build(
                        tenant_id=tenant_id,
                        run_id=agent.run_id,
                        event_type=EventType.RUN_COMPLETED,
                        payload={"result": decision.final_output},
                    )
                )
            return decision.final_output or ""

        worker_role = ensure_predefined_worker(decision.worker_role)
        worker = AgentRecord(
            run_id=agent.run_id,
            role=worker_role,
            status=AgentStatus.READY,
            objective=decision.task_input or "",
            parent_agent_id=agent.agent_id,
        )
        task = TaskRecord(
            run_id=agent.run_id,
            parent_agent_id=agent.agent_id,
            worker_agent_id=worker.agent_id,
            worker_role=worker_role,
            objective=decision.task_input or "",
        )
        worker.task_id = task.task_id
        await self._repository.add_agent(worker)
        await self._repository.add_task(task)
        await self._emit(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=agent.run_id,
                agent_id=agent.agent_id,
                event_type=EventType.TASK_DISPATCHED,
                payload={"task_id": task.task_id, "worker_role": worker.role.value, "objective": worker.objective},
            )
        )

        worker_result = await self._run_agent(tenant_id, worker.agent_id)
        merged_observations = [*agent.observations, f"{worker.role.value}:{worker_result}"]
        await self._repository.update_task_state(task.task_id, status=TaskStatus.COMPLETED, result=worker_result)
        await self._repository.update_agent_state(agent.agent_id, observations=merged_observations)
        return await self._run_agent(tenant_id, agent.agent_id)

    async def _emit(self, event: RuntimeEvent) -> None:
        await self._repository.append_event(event)
        await self._event_hub.publish(event)
```

```python
# src/agent_runtime/runtime/services.py
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from agent_runtime.domain.enums import AgentRole, EventType, RunStatus
from agent_runtime.domain.models import AgentRecord, RunRecord, RuntimeEvent
from agent_runtime.models.base import ModelClient
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.runtime.resume import ResumeCoordinator


class RunService:
    def __init__(self, repository: RuntimeRepository, model_client: ModelClient, event_hub: EventStreamHub) -> None:
        self._repository = repository
        self._event_hub = event_hub
        self._orchestrator = RuntimeOrchestrator(repository, model_client, event_hub)
        self._resume = ResumeCoordinator(repository, self._orchestrator)

    async def create_run(self, tenant_id: str, objective: str) -> RunRecord:
        run = RunRecord(tenant_id=tenant_id, objective=objective)
        supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=objective)
        await self._repository.create_run(run, supervisor)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=tenant_id,
                run_id=run.run_id,
                agent_id=supervisor.agent_id,
                event_type=EventType.RUN_CREATED,
                payload={"objective": objective},
            )
        )
        asyncio.create_task(self._orchestrator.execute_run(run.run_id))
        return run

    async def get_run(self, run_id: str) -> RunRecord:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        return run

    async def resume_run(self, run_id: str) -> RunRecord:
        await self._resume.resume_run(run_id)
        return await self.get_run(run_id)

    async def cancel_run(self, run_id: str) -> None:
        run = await self.get_run(run_id)
        await self._repository.update_run_status(run_id, RunStatus.CANCELLED)
        await self._repository.append_event(
            RuntimeEvent.build(
                tenant_id=run.tenant_id,
                run_id=run_id,
                event_type=EventType.RUN_CANCELLED,
                payload={"reason": "cancelled by api"},
            )
        )

    async def replay_events(self, run_id: str) -> list[RuntimeEvent]:
        return await self._repository.list_events(run_id)

    async def stream_events(self, run_id: str) -> AsyncIterator[str]:
        persisted = await self._repository.list_events(run_id)
        for event in persisted:
            yield f"data: {event.model_dump_json()}\n\n"
        async for event in self._event_hub.subscribe(run_id):
            yield f"data: {event.model_dump_json()}\n\n"
```

- [ ] **Step 4: Run the multi-agent integration test**

Run: `pytest tests/integration/test_multi_agent_flow.py -v`
Expected: PASS

- [ ] **Step 5: Run the focused integration suite and commit**

Run: `pytest tests/integration/test_run_lifecycle.py tests/integration/test_resume_flow.py tests/integration/test_multi_agent_flow.py -v`
Expected: PASS

```bash
git add src/agent_runtime/agents src/agent_runtime/runtime tests/integration/test_multi_agent_flow.py
git commit -m "feat: add supervisor worker orchestration"
```

## Task 7: Wire Resume And SSE APIs Cleanly

**Files:**
- Modify: `src/agent_runtime/api/routes/runs.py`
- Modify: `src/agent_runtime/api/schemas.py`
- Modify: `tests/integration/test_run_lifecycle.py`

- [ ] **Step 1: Add a failing API assertion for explicit resume and cancel endpoints**

```python
# tests/integration/test_run_lifecycle.py
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient


@pytest.mark.asyncio
async def test_cancel_endpoint_marks_run_cancelled(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {"supervisor": [ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="final answer")]}
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "summarize incident"},
        )
        run_id = create_response.json()["run_id"]
        cancel_response = await client.post(f"/v1/runs/{run_id}/cancel")

        assert cancel_response.status_code == 202

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] in {"cancelled", "completed"}:
                break
            await asyncio.sleep(0.05)

        assert payload["status"] in {"cancelled", "completed"}
```

- [ ] **Step 2: Run the lifecycle tests to verify the new assertion fails or is flaky**

Run: `pytest tests/integration/test_run_lifecycle.py -v`
Expected: FAIL or FLAKY because cancel and resume semantics are not yet exposed consistently

- [ ] **Step 3: Finalize API contracts for resume and stable event replay**

```python
# src/agent_runtime/api/schemas.py
from pydantic import BaseModel


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


class EventReplayResponse(BaseModel):
    events: list[dict]
```

```python
# src/agent_runtime/api/routes/runs.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent_runtime.api.schemas import ActionAcceptedResponse, CreateRunRequest, EventReplayResponse, RunResponse

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(request: Request, payload: CreateRunRequest) -> RunResponse:
    run = await request.app.state.run_service.create_run(payload.tenant_id, payload.objective)
    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(request: Request, run_id: str) -> RunResponse:
    try:
        run = await request.app.state.run_service.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(request: Request, run_id: str) -> RunResponse:
    run = await request.app.state.run_service.resume_run(run_id)
    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.post("/{run_id}/cancel", response_model=ActionAcceptedResponse, status_code=202)
async def cancel_run(request: Request, run_id: str) -> ActionAcceptedResponse:
    await request.app.state.run_service.cancel_run(run_id)
    return ActionAcceptedResponse(status="accepted")


@router.get("/{run_id}/events")
async def stream_events(request: Request, run_id: str) -> StreamingResponse:
    return StreamingResponse(
        request.app.state.run_service.stream_events(run_id),
        media_type="text/event-stream",
    )


@router.get("/{run_id}/events/replay", response_model=EventReplayResponse)
async def replay_events(request: Request, run_id: str) -> EventReplayResponse:
    events = await request.app.state.run_service.replay_events(run_id)
    return EventReplayResponse(events=[event.model_dump(mode="json") for event in events])
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api tests/integration/test_run_lifecycle.py
git commit -m "feat: finalize run resume and event api contracts"
```

## Task 8: Add Minimal Shared Test Fixtures

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Add a failing import from shared fixtures to one integration test**

```python
# tests/integration/test_app_smoke.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_fixture_backed_client_runs_healthcheck(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the smoke test to verify the shared fixture is missing**

Run: `pytest tests/integration/test_app_smoke.py -v`
Expected: FAIL with `fixture 'api_client' not found`

- [ ] **Step 3: Add real shared fixtures**

```python
# tests/conftest.py
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient


@pytest.fixture
def scripted_supervisor_client() -> ScriptedModelClient:
    return ScriptedModelClient(
        {"supervisor": [ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="fixture result")]}
    )


@pytest.fixture
async def api_client(tmp_path, scripted_supervisor_client) -> AsyncIterator[AsyncClient]:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=scripted_supervisor_client,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
```

```python
# tests/integration/test_app_smoke.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_fixture_backed_client_runs_healthcheck(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 4: Run the smoke and lifecycle tests**

Run: `pytest tests/integration/test_app_smoke.py tests/integration/test_run_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration/test_app_smoke.py
git commit -m "test: add shared runtime api fixtures"
```

## Self-Review Checklist

### Spec Coverage

- `API-first runtime`
  Covered by Tasks 1, 4, 5, and 7.
- `single-supervisor resilient core`
  Covered by Tasks 2, 3, 4, and 5.
- `full resumability`
  Covered by Tasks 3 and 5.
- `supervisor-worker orchestration`
  Covered by Task 6.
- `logical multi-tenancy`
  Tenant id exists in domain models, events, repositories, and APIs in Tasks 2 through 7.
- `streaming runtime events`
  Covered by Task 4 and stabilized in Task 7.

### Plan Cleanliness

- The plan intentionally excludes tools, approval workflows, and production hardening because this document is scoped to `M1 + M2`.
- No step above should retain temporary code, pseudo-method names, or undefined file paths once executed.

### Type Consistency

- Domain object names are fixed as `RunRecord`, `AgentRecord`, `TaskRecord`, `CheckpointRecord`, and `RuntimeEvent`.
- Runtime service names are fixed as `RunService`, `RuntimeOrchestrator`, and `ResumeCoordinator`.
- Role strings are fixed as `supervisor`, `researcher`, and `tool-runner`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-16-agent-runtime-core-m1-m2.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
