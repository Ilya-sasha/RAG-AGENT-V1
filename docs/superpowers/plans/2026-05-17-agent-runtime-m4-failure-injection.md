# Agent Runtime M4 Failure Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic fault injection layer for model and tool failures so tests can force runtime failures at explicit execution boundaries and verify failure-state correctness.

**Architecture:** This phase introduces a small `FaultInjector` abstraction with a no-op default and a rule-based test implementation. `create_app(...)`, `RunService`, and `RuntimeOrchestrator` accept the injector, and selected runtime/model/tool boundaries call `trigger(...)` without introducing any injected-fault-specific recovery path.

**Tech Stack:** Python 3.11+, FastAPI, pytest, pytest-asyncio, httpx, existing runtime/orchestrator services

---

## File Structure

### Create

- `src/agent_runtime/testing/faults.py`
  Fault point enum, rule model, no-op injector, and deterministic rule-based injector.
- `tests/unit/test_fault_injection.py`
  Unit tests for rule matching and injector semantics.

### Modify

- `src/agent_runtime/api/app.py`
  Accept an optional `fault_injector` and pass it into `RunService`.
- `src/agent_runtime/runtime/services.py`
  Store the injector, pass it into `RuntimeOrchestrator`, and trigger runtime-level fault points.
- `src/agent_runtime/runtime/orchestrator.py`
  Trigger model/tool fault points.
- `tests/integration/test_run_lifecycle.py`
  Add injected model failure and injected resume-entry failure tests.
- `tests/integration/test_tool_approval_flow.py`
  Add injected tool execution and tool-resume failure tests.

## Task 1: Add Fault Injection Foundations

**Files:**
- Create: `src/agent_runtime/testing/faults.py`
- Test: `tests/unit/test_fault_injection.py`

- [ ] **Step 1: Write the failing unit tests for the fault injector**

```python
# tests/unit/test_fault_injection.py
import pytest

from agent_runtime.testing.faults import (
    FaultPoint,
    FaultRule,
    NoopFaultInjector,
    RuleBasedFaultInjector,
)


def test_noop_fault_injector_never_raises() -> None:
    injector = NoopFaultInjector()
    injector.trigger(FaultPoint.MODEL_BEFORE_COMPLETE, run_id="run-1")


def test_rule_based_fault_injector_raises_on_matching_count() -> None:
    injector = RuleBasedFaultInjector(
        [
            FaultRule(
                point=FaultPoint.MODEL_BEFORE_COMPLETE,
                times=2,
                exception_factory=lambda: RuntimeError("injected model failure"),
            )
        ]
    )

    injector.trigger(FaultPoint.MODEL_BEFORE_COMPLETE, run_id="run-1")

    with pytest.raises(RuntimeError, match="injected model failure"):
        injector.trigger(FaultPoint.MODEL_BEFORE_COMPLETE, run_id="run-1")


def test_rule_based_fault_injector_does_not_raise_after_count_passes() -> None:
    injector = RuleBasedFaultInjector(
        [
            FaultRule(
                point=FaultPoint.TOOL_BEFORE_EXECUTE,
                times=1,
                exception_factory=lambda: RuntimeError("injected tool failure"),
            )
        ]
    )

    with pytest.raises(RuntimeError, match="injected tool failure"):
        injector.trigger(FaultPoint.TOOL_BEFORE_EXECUTE, tool_name="payment-api")

    injector.trigger(FaultPoint.TOOL_BEFORE_EXECUTE, tool_name="payment-api")
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `pytest tests/unit/test_fault_injection.py -v`
Expected: FAIL with missing `agent_runtime.testing.faults`

- [ ] **Step 3: Add the minimal fault injection module**

```python
# src/agent_runtime/testing/faults.py
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class FaultPoint(StrEnum):
    RUN_CREATE_BEFORE_DISPATCH = "run_create_before_dispatch"
    RUN_RESUME_BEFORE_EXECUTE = "run_resume_before_execute"
    MODEL_BEFORE_COMPLETE = "model_before_complete"
    TOOL_BEFORE_EXECUTE = "tool_before_execute"
    TOOL_BEFORE_RESUME = "tool_before_resume"


@dataclass(frozen=True, slots=True)
class FaultRule:
    point: FaultPoint
    times: int
    exception_factory: Callable[[], Exception]


class FaultInjector(Protocol):
    def trigger(self, point: FaultPoint, **context: Any) -> None: ...


class NoopFaultInjector:
    def trigger(self, point: FaultPoint, **context: Any) -> None:
        del point, context


class RuleBasedFaultInjector:
    def __init__(self, rules: Sequence[FaultRule]) -> None:
        self._rules = list(rules)
        self._counts: dict[FaultPoint, int] = defaultdict(int)
        self._fired_rule_indexes: set[int] = set()

    def trigger(self, point: FaultPoint, **context: Any) -> None:
        del context
        self._counts[point] += 1
        count = self._counts[point]
        for index, rule in enumerate(self._rules):
            if index in self._fired_rule_indexes:
                continue
            if rule.point == point and rule.times == count:
                self._fired_rule_indexes.add(index)
                raise rule.exception_factory()
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `pytest tests/unit/test_fault_injection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/testing/faults.py tests/unit/test_fault_injection.py
git commit -m "feat: add fault injection foundations"
```

## Task 2: Wire Fault Injector Through App And Runtime Boundaries

**Files:**
- Modify: `src/agent_runtime/api/app.py`
- Modify: `src/agent_runtime/runtime/services.py`
- Modify: `src/agent_runtime/runtime/orchestrator.py`
- Test: `tests/integration/test_run_lifecycle.py`

- [ ] **Step 1: Write the failing integration test for injected model failure**

```python
# tests/integration/test_run_lifecycle.py
import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import RunStatus
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.models.base import ModelDecision
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.testing.faults import FaultPoint, FaultRule, RuleBasedFaultInjector


@pytest.mark.asyncio
async def test_injected_model_failure_marks_run_failed(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {"supervisor": [ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="ok")]}
        ),
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.MODEL_BEFORE_COMPLETE,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected model failure"),
                )
            ]
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        create_response = await client.post("/v1/runs", json={"tenant_id": "tenant-a", "objective": "observe"})
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "failed":
                break

    assert payload["status"] == RunStatus.FAILED.value
    assert "injected model failure" in payload["error"]
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run: `pytest tests/integration/test_run_lifecycle.py::test_injected_model_failure_marks_run_failed -v`
Expected: FAIL because `create_app(...)` and runtime services do not accept `fault_injector`

- [ ] **Step 3: Wire `fault_injector` through app, service, and orchestrator**

```python
# src/agent_runtime/api/app.py
from agent_runtime.testing.faults import FaultInjector, NoopFaultInjector

def create_app(..., fault_injector: FaultInjector | None = None) -> FastAPI:
    runtime_fault_injector = fault_injector or NoopFaultInjector()
    ...
    app.state.run_service = RunService(
        repository,
        model_client or ScriptedModelClient({"supervisor": []}),
        event_hub,
        tool_gateway=tool_gateway,
        metrics_sink=metrics_sink,
        runtime_logger=runtime_logger,
        fault_injector=runtime_fault_injector,
    )
```

```python
# src/agent_runtime/runtime/services.py
from agent_runtime.testing.faults import FaultInjector, FaultPoint, NoopFaultInjector

class RunService:
    def __init__(..., fault_injector: FaultInjector | None = None) -> None:
        self._fault_injector = fault_injector or NoopFaultInjector()
        self._orchestrator = RuntimeOrchestrator(
            repository,
            model_client,
            event_hub,
            tool_gateway=tool_gateway,
            metrics_sink=metrics_sink,
            runtime_logger=self._runtime_logger,
            fault_injector=self._fault_injector,
        )

    async def create_run(self, tenant_id: str, objective: str) -> RunRecord:
        ...
        self._fault_injector.trigger(
            FaultPoint.RUN_CREATE_BEFORE_DISPATCH,
            tenant_id=tenant_id,
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
        )
        self._tasks[run.run_id] = asyncio.create_task(self._execute_run(run.run_id))

    async def resume_run(self, run_id: str) -> RunRecord:
        ...
        self._tasks[run_id] = asyncio.create_task(self._execute_run(run_id, is_resume=True))
```

```python
# src/agent_runtime/runtime/orchestrator.py
from agent_runtime.testing.faults import FaultInjector, FaultPoint, NoopFaultInjector

class RuntimeOrchestrator:
    def __init__(..., fault_injector: FaultInjector | None = None) -> None:
        self._fault_injector = fault_injector or NoopFaultInjector()

    async def _run_agent(...):
        ...
        self._fault_injector.trigger(
            FaultPoint.MODEL_BEFORE_COMPLETE,
            tenant_id=tenant_id,
            run_id=agent.run_id,
            agent_id=agent.agent_id,
        )
        decision = await self._model_client.complete(...)
```

- [ ] **Step 4: Run the injected model failure test to verify it passes**

Run: `pytest tests/integration/test_run_lifecycle.py::test_injected_model_failure_marks_run_failed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api/app.py src/agent_runtime/runtime/services.py src/agent_runtime/runtime/orchestrator.py tests/integration/test_run_lifecycle.py
git commit -m "feat: wire fault injector through runtime"
```

## Task 3: Add Resume-Entry Failure Injection Coverage

**Files:**
- Modify: `tests/integration/test_run_lifecycle.py`
- Modify: `src/agent_runtime/runtime/services.py`

- [ ] **Step 1: Write the failing resume-entry injection test**

```python
# tests/integration/test_run_lifecycle.py
@pytest.mark.asyncio
async def test_injected_resume_entry_failure_marks_run_failed(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {"supervisor": [ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="ok")]}
        ),
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.RUN_RESUME_BEFORE_EXECUTE,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected resume failure"),
                )
            ]
        ),
    )
    await app.state.ensure_initialized()
    repository = app.state.run_service._repository
    run = RunRecord(tenant_id="tenant-a", objective="recover this run", status=RunStatus.RUNNING)
    supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=run.objective)
    await repository.create_run(run, supervisor)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/v1/runs/{run.run_id}/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "injected resume failure" in response.json()["error"]
```

- [ ] **Step 2: Run the resume-entry test to verify it fails**

Run: `pytest tests/integration/test_run_lifecycle.py::test_injected_resume_entry_failure_marks_run_failed -v`
Expected: FAIL because `resume_run()` does not trigger `RUN_RESUME_BEFORE_EXECUTE`

- [ ] **Step 3: Trigger resume-entry fault injection before resumed execution**

```python
# src/agent_runtime/runtime/services.py
    async def resume_run(self, run_id: str) -> RunRecord:
        ...
        self._fault_injector.trigger(FaultPoint.RUN_RESUME_BEFORE_EXECUTE, run_id=run_id)
        self._tasks[run_id] = asyncio.create_task(self._execute_run(run_id))
```

- [ ] **Step 4: Run the resume-entry test to verify it passes**

Run: `pytest tests/integration/test_run_lifecycle.py::test_injected_resume_entry_failure_marks_run_failed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/runtime/services.py tests/integration/test_run_lifecycle.py
git commit -m "feat: add resume entry failure injection"
```

## Task 4: Add Tool Execution And Tool Resume Failure Injection Coverage

**Files:**
- Modify: `src/agent_runtime/runtime/orchestrator.py`
- Modify: `tests/integration/test_tool_approval_flow.py`

- [ ] **Step 1: Write the failing injected tool execution test**

```python
# tests/integration/test_tool_approval_flow.py
@pytest.mark.asyncio
async def test_injected_tool_execution_failure_marks_run_failed(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register("payment-api", RecordingExecutor({"status": "ok"}))
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {"supervisor": [ModelDecision(kind=DecisionKind.CALL_TOOL, summary="call", tool_name="payment-api", tool_arguments={"amount": 10})]}
        ),
        tool_registry=registry,
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.TOOL_BEFORE_EXECUTE,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected tool failure"),
                )
            ]
        ),
    )
    ...
    assert payload["status"] == "failed"
    assert "injected tool failure" in payload["error"]
```

```python
# tests/integration/test_tool_approval_flow.py
@pytest.mark.asyncio
async def test_injected_tool_resume_failure_marks_run_failed(tmp_path) -> None:
    ...
    fault_injector=RuleBasedFaultInjector(
        [
            FaultRule(
                point=FaultPoint.TOOL_BEFORE_RESUME,
                times=1,
                exception_factory=lambda: RuntimeError("injected tool resume failure"),
            )
        ]
    )
    ...
    assert payload["status"] == "failed"
    assert "injected tool resume failure" in payload["error"]
```

- [ ] **Step 2: Run the targeted tool fault tests to verify they fail**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_injected_tool_execution_failure_marks_run_failed tests/integration/test_tool_approval_flow.py::test_injected_tool_resume_failure_marks_run_failed -v`
Expected: FAIL because orchestrator does not trigger tool fault points

- [ ] **Step 3: Trigger tool fault points before execute and before approved resume**

```python
# src/agent_runtime/runtime/orchestrator.py
    async def _call_tool_from_agent(...):
        ...
        self._fault_injector.trigger(
            FaultPoint.TOOL_BEFORE_EXECUTE,
            tenant_id=tenant_id,
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            tool_name=decision.tool_name or "",
        )
        outcome = await self._tool_gateway.execute(...)
```

```python
# src/agent_runtime/runtime/orchestrator.py
    async def _resume_waiting_tool_if_present(...):
        ...
        self._fault_injector.trigger(
            FaultPoint.TOOL_BEFORE_RESUME,
            tenant_id=tenant_id,
            run_id=agent.run_id,
            agent_id=agent.agent_id,
            tool_name=tool_name,
        )
        outcome = await self._tool_gateway.resume_approved_invocation(invocation_id)
```

- [ ] **Step 4: Run the targeted tool fault tests to verify they pass**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_injected_tool_execution_failure_marks_run_failed tests/integration/test_tool_approval_flow.py::test_injected_tool_resume_failure_marks_run_failed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/runtime/orchestrator.py tests/integration/test_tool_approval_flow.py
git commit -m "feat: add tool fault injection coverage"
```

## Task 5: Final Failure Injection Regression Pass

**Files:**
- Test: `tests/unit/test_fault_injection.py`
- Test: `tests/integration/test_run_lifecycle.py`
- Test: `tests/integration/test_tool_approval_flow.py`
- Test: `tests/integration/test_multi_agent_flow.py`
- Test: `tests/integration/test_resume_flow.py`
- Test: `tests/unit/test_observability.py`

- [ ] **Step 1: Run the focused failure injection suite**

Run: `pytest tests/unit/test_fault_injection.py tests/integration/test_run_lifecycle.py tests/integration/test_tool_approval_flow.py -v`
Expected: PASS

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/agent_runtime tests
git commit -m "test: verify fault injection failure paths"
```

## Self-Review Checklist

### Spec Coverage

- `FaultInjector abstraction`
  Covered by Task 1.
- `runtime-node + model/tool fault points`
  Covered by Tasks 2, 3, and 4.
- `test-only explicit configuration`
  Covered by Tasks 2, 3, and 4 through `create_app(..., fault_injector=...)`.
- `failure-state correctness`
  Covered by Tasks 2, 3, 4, and 5.

### Plan Cleanliness

- The plan keeps injected faults on existing runtime boundaries instead of adding a second failure pipeline.
- The plan does not expose API, env, or config-file control for faults.
- Commit steps remain placeholders because this workspace is not a git repository.

### Type Consistency

- Core types are `FaultPoint`, `FaultRule`, `FaultInjector`, `NoopFaultInjector`, and `RuleBasedFaultInjector`.
- Runtime integration parameter is named `fault_injector`.
- Trigger API is named `trigger(...)` everywhere.
