# Agent Runtime M4 Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-oriented structured logging and Prometheus-compatible metrics to the runtime core without changing orchestration behavior.

**Architecture:** This phase adds a thin `observability` package that exposes request context helpers, structured logging helpers, and a `MetricsSink` abstraction backed by `prometheus_client`. Existing FastAPI, `RunService`, and `RuntimeOrchestrator` code emit observability signals through this boundary, while `/metrics` exports in-memory registry state without database reads.

**Tech Stack:** Python 3.11+, FastAPI, Prometheus `prometheus_client`, pytest, pytest-asyncio, httpx

---

## File Structure

### Create

- `src/agent_runtime/observability/context.py`
  Request-scoped correlation context helpers.
- `src/agent_runtime/observability/logging.py`
  Structured logger adapter with best-effort emission.
- `src/agent_runtime/observability/metrics.py`
  `MetricsSink` abstraction and Prometheus-backed implementation.
- `src/agent_runtime/api/routes/metrics.py`
  `GET /metrics` endpoint.
- `tests/unit/test_observability.py`
  Unit tests for metrics export and structured log payload behavior.

### Modify

- `pyproject.toml`
  Add `prometheus_client` dependency.
- `src/agent_runtime/api/app.py`
  Initialize observability services, add request middleware, include metrics router.
- `src/agent_runtime/runtime/services.py`
  Emit run and approval logs and metrics.
- `src/agent_runtime/runtime/orchestrator.py`
  Emit run, agent, tool, and approval-wait logs and metrics.
- `tests/integration/test_app_smoke.py`
  Add `/metrics` smoke test.
- `tests/integration/test_run_lifecycle.py`
  Add run lifecycle metrics assertions.
- `tests/integration/test_tool_approval_flow.py`
  Add approval and tool metrics assertions.

## Task 1: Add Observability Foundations

**Files:**
- Modify: `pyproject.toml`
- Create: `src/agent_runtime/observability/context.py`
- Create: `src/agent_runtime/observability/logging.py`
- Create: `src/agent_runtime/observability/metrics.py`
- Test: `tests/unit/test_observability.py`

- [ ] **Step 1: Write the failing unit tests for metrics export and structured log payloads**

```python
# tests/unit/test_observability.py
import json
import logging

from agent_runtime.observability.logging import build_log_payload, emit_structured_log
from agent_runtime.observability.metrics import PrometheusMetricsSink


def test_prometheus_metrics_sink_exports_expected_counters() -> None:
    sink = PrometheusMetricsSink()

    sink.record_run_created()
    sink.record_http_request(method="GET", route="/health", status_code=200, duration_seconds=0.01)

    payload = sink.render_prometheus_text()

    assert "runtime_runs_created_total" in payload
    assert 'http_requests_total{method="GET",route="/health",status_code="200"} 1.0' in payload


def test_build_log_payload_merges_context_and_fields() -> None:
    payload = build_log_payload(
        "run created",
        component="run_service",
        context={"request_id": "req-1", "run_id": "run-1"},
        fields={"status": "created"},
    )

    assert payload["message"] == "run created"
    assert payload["component"] == "run_service"
    assert payload["request_id"] == "req-1"
    assert payload["run_id"] == "run-1"
    assert payload["status"] == "created"


def test_emit_structured_log_does_not_raise_when_handler_fails() -> None:
    class FailingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("boom")

    logger = logging.getLogger("test.observability")
    logger.handlers = [FailingHandler()]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    emit_structured_log(logger, "safe", component="test", context={}, fields={})
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `pytest tests/unit/test_observability.py -v`
Expected: FAIL with missing `agent_runtime.observability` modules

- [ ] **Step 3: Add the minimal dependency and observability foundation modules**

```toml
# pyproject.toml
dependencies = [
  "fastapi>=0.115.0,<1.0.0",
  "uvicorn>=0.30.0,<1.0.0",
  "pydantic>=2.8.0,<3.0.0",
  "sqlalchemy>=2.0.36,<3.0.0",
  "aiosqlite>=0.20.0,<1.0.0",
  "httpx>=0.27.0,<1.0.0",
  "prometheus-client>=0.21.0,<1.0.0",
]
```

```python
# src/agent_runtime/observability/context.py
from __future__ import annotations

from contextvars import ContextVar

_REQUEST_CONTEXT: ContextVar[dict[str, str]] = ContextVar("request_context", default={})


def get_request_context() -> dict[str, str]:
    return dict(_REQUEST_CONTEXT.get())


def bind_request_context(**fields: str | None) -> object:
    current = get_request_context()
    current.update({key: value for key, value in fields.items() if value is not None})
    return _REQUEST_CONTEXT.set(current)


def reset_request_context(token: object) -> None:
    _REQUEST_CONTEXT.reset(token)
```

```python
# src/agent_runtime/observability/logging.py
from __future__ import annotations

import json
import logging
from typing import Any


def build_log_payload(
    message: str,
    *,
    component: str,
    context: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    payload = {"message": message, "component": component}
    payload.update(context)
    payload.update(fields)
    return payload


def emit_structured_log(
    logger: logging.Logger,
    message: str,
    *,
    component: str,
    context: dict[str, Any],
    fields: dict[str, Any],
) -> None:
    try:
        payload = build_log_payload(message, component=component, context=context, fields=fields)
        logger.info(json.dumps(payload, sort_keys=True, default=str))
    except Exception:
        return
```

```python
# src/agent_runtime/observability/metrics.py
from __future__ import annotations

from typing import Protocol

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


class MetricsSink(Protocol):
    def record_http_request(self, *, method: str, route: str, status_code: int, duration_seconds: float) -> None: ...
    def record_run_created(self) -> None: ...
    def render_prometheus_text(self) -> str: ...


class PrometheusMetricsSink:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or CollectorRegistry()
        self._http_requests = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "route", "status_code"],
            registry=self._registry,
        )
        self._http_request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration",
            ["method", "route", "status_code"],
            registry=self._registry,
        )
        self._runs_created = Counter(
            "runtime_runs_created_total",
            "Runtime runs created",
            registry=self._registry,
        )

    def record_http_request(self, *, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        labels = {"method": method, "route": route, "status_code": str(status_code)}
        self._http_requests.labels(**labels).inc()
        self._http_request_duration.labels(**labels).observe(duration_seconds)

    def record_run_created(self) -> None:
        self._runs_created.inc()

    def render_prometheus_text(self) -> str:
        return generate_latest(self._registry).decode("utf-8")
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `pytest tests/unit/test_observability.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/agent_runtime/observability tests/unit/test_observability.py
git commit -m "feat: add observability foundations"
```

## Task 2: Add Metrics Endpoint And HTTP Request Instrumentation

**Files:**
- Create: `src/agent_runtime/api/routes/metrics.py`
- Modify: `src/agent_runtime/api/app.py`
- Test: `tests/integration/test_app_smoke.py`

- [ ] **Step 1: Write the failing integration test for `/metrics` and request counters**

```python
# tests/integration/test_app_smoke.py
import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app


@pytest.mark.asyncio
async def test_metrics_endpoint_exports_prometheus_text(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        health_response = await client.get("/health")
        metrics_response = await client.get("/metrics")

    assert health_response.status_code == 200
    assert metrics_response.status_code == 200
    assert "http_requests_total" in metrics_response.text
    assert 'route="/health"' in metrics_response.text
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run: `pytest tests/integration/test_app_smoke.py::test_metrics_endpoint_exports_prometheus_text -v`
Expected: FAIL with missing `/metrics` route or missing request metrics

- [ ] **Step 3: Add `/metrics` route and request middleware instrumentation**

```python
# src/agent_runtime/api/routes/metrics.py
from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    payload = request.app.state.metrics_sink.render_prometheus_text()
    return Response(content=payload, media_type="text/plain; version=0.0.4; charset=utf-8")
```

```python
# src/agent_runtime/api/app.py
import time
from uuid import uuid4

from agent_runtime.api.routes.metrics import router as metrics_router
from agent_runtime.observability.context import bind_request_context, reset_request_context
from agent_runtime.observability.logging import emit_structured_log
from agent_runtime.observability.metrics import PrometheusMetricsSink

metrics_sink = PrometheusMetricsSink()
app.state.metrics_sink = metrics_sink

@app.middleware("http")
async def instrument_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    token = bind_request_context(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        duration = time.perf_counter() - started
        status_code = response.status_code if "response" in locals() else 500
        request.app.state.metrics_sink.record_http_request(
            method=request.method,
            route=request.url.path,
            status_code=status_code,
            duration_seconds=duration,
        )
        reset_request_context(token)

app.include_router(metrics_router)
```

- [ ] **Step 4: Run the metrics integration test to verify it passes**

Run: `pytest tests/integration/test_app_smoke.py::test_metrics_endpoint_exports_prometheus_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api/app.py src/agent_runtime/api/routes/metrics.py tests/integration/test_app_smoke.py
git commit -m "feat: add metrics endpoint and request instrumentation"
```

## Task 3: Instrument RunService Lifecycle And Approval Flow

**Files:**
- Modify: `src/agent_runtime/runtime/services.py`
- Modify: `tests/integration/test_run_lifecycle.py`
- Modify: `tests/integration/test_tool_approval_flow.py`

- [ ] **Step 1: Write the failing integration tests for run and approval metrics**

```python
# tests/integration/test_run_lifecycle.py
@pytest.mark.asyncio
async def test_run_lifecycle_updates_metrics_endpoint(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {"supervisor": [ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="ok")]}
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        create_response = await client.post("/v1/runs", json={"tenant_id": "tenant-a", "objective": "observe"})
        metrics_response = await client.get("/metrics")

    assert create_response.status_code == 201
    assert "runtime_runs_created_total" in metrics_response.text
    assert "runtime_runs_completed_total" in metrics_response.text
```

```python
# tests/integration/test_tool_approval_flow.py
assert "runtime_approval_resolutions_total" in metrics_response.text
assert 'status="approved"' in metrics_response.text
```

- [ ] **Step 2: Run the targeted integration tests to verify they fail**

Run: `pytest tests/integration/test_run_lifecycle.py::test_run_lifecycle_updates_metrics_endpoint tests/integration/test_tool_approval_flow.py::test_approval_approve_endpoint_resolves_request_and_resumes_run -v`
Expected: FAIL with missing run and approval metrics

- [ ] **Step 3: Add lifecycle counters and structured logs in `RunService`**

```python
# src/agent_runtime/runtime/services.py
class RunService:
    def __init__(..., metrics_sink: MetricsSink | None = None, runtime_logger: logging.Logger | None = None) -> None:
        self._metrics_sink = metrics_sink
        self._runtime_logger = runtime_logger or logging.getLogger("agent_runtime.runtime")

    async def create_run(self, tenant_id: str, objective: str) -> RunRecord:
        ...
        if self._metrics_sink is not None:
            self._metrics_sink.record_run_created()
        emit_structured_log(
            self._runtime_logger,
            "run created",
            component="run_service",
            context={"tenant_id": tenant_id, "run_id": run.run_id, "agent_id": supervisor.agent_id},
            fields={"status": run.status.value},
        )
        ...

    async def approve_approval(self, approval_id: str, *, resolution_note: str | None = None) -> None:
        ...
        if self._metrics_sink is not None:
            self._metrics_sink.record_approval_resolution(status="approved")

    async def reject_approval(self, approval_id: str, *, resolution_note: str | None = None) -> None:
        ...
        if self._metrics_sink is not None:
            self._metrics_sink.record_approval_resolution(status="rejected")
```

- [ ] **Step 4: Run the targeted integration tests to verify they pass**

Run: `pytest tests/integration/test_run_lifecycle.py::test_run_lifecycle_updates_metrics_endpoint tests/integration/test_tool_approval_flow.py::test_approval_approve_endpoint_resolves_request_and_resumes_run -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/runtime/services.py tests/integration/test_run_lifecycle.py tests/integration/test_tool_approval_flow.py
git commit -m "feat: instrument run service lifecycle"
```

## Task 4: Instrument RuntimeOrchestrator Agent And Tool Flows

**Files:**
- Modify: `src/agent_runtime/runtime/orchestrator.py`
- Modify: `tests/integration/test_tool_approval_flow.py`
- Modify: `tests/integration/test_multi_agent_flow.py`

- [ ] **Step 1: Write the failing integration tests for decision and tool metrics**

```python
# tests/integration/test_tool_approval_flow.py
assert "runtime_tool_calls_total" in metrics_response.text
assert 'tool_name="payment-api"' in metrics_response.text
```

```python
# tests/integration/test_multi_agent_flow.py
assert "runtime_agent_decisions_total" in metrics_response.text
assert 'kind="delegate"' in metrics_response.text
```

- [ ] **Step 2: Run the targeted integration tests to verify they fail**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_run_waits_for_approval_then_resumes_tool_execution tests/integration/test_multi_agent_flow.py::test_supervisor_dispatches_worker_and_merges_result -v`
Expected: FAIL with missing agent decision or tool metrics

- [ ] **Step 3: Add agent and tool instrumentation in `RuntimeOrchestrator`**

```python
# src/agent_runtime/runtime/orchestrator.py
started = time.perf_counter()
decision = await self._model_client.complete(...)
if self._metrics_sink is not None:
    self._metrics_sink.record_agent_decision(kind=decision.kind.value)

tool_started = time.perf_counter()
outcome = await self._tool_gateway.execute(...)
if self._metrics_sink is not None:
    self._metrics_sink.record_tool_call(
        tool_name=decision.tool_name or "",
        status=outcome.status.value,
        duration_seconds=time.perf_counter() - tool_started,
    )
```

- [ ] **Step 4: Run the targeted integration tests to verify they pass**

Run: `pytest tests/integration/test_tool_approval_flow.py::test_run_waits_for_approval_then_resumes_tool_execution tests/integration/test_multi_agent_flow.py::test_supervisor_dispatches_worker_and_merges_result -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/runtime/orchestrator.py tests/integration/test_tool_approval_flow.py tests/integration/test_multi_agent_flow.py
git commit -m "feat: instrument orchestrator flows"
```

## Task 5: Final Observability Regression Pass

**Files:**
- Test: `tests/unit/test_observability.py`
- Test: `tests/integration/test_app_smoke.py`
- Test: `tests/integration/test_run_lifecycle.py`
- Test: `tests/integration/test_tool_approval_flow.py`
- Test: `tests/integration/test_multi_agent_flow.py`
- Test: `tests/integration/test_resume_flow.py`
- Test: `tests/unit/test_tool_gateway.py`

- [ ] **Step 1: Run the focused observability suite**

Run: `pytest tests/unit/test_observability.py tests/integration/test_app_smoke.py tests/integration/test_run_lifecycle.py tests/integration/test_tool_approval_flow.py tests/integration/test_multi_agent_flow.py -v`
Expected: PASS

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/agent_runtime tests
git commit -m "test: verify observability instrumentation"
```

## Self-Review Checklist

### Spec Coverage

- `structured logging`
  Covered by Tasks 1, 2, 3, and 4.
- `Prometheus /metrics`
  Covered by Tasks 1 and 2.
- `run, approval, agent, tool metrics`
  Covered by Tasks 3 and 4.
- `regression safety`
  Covered by Task 5.
- `tracing deferred`
  Preserved because no task adds tracing libraries or span wiring.

### Plan Cleanliness

- The plan keeps instrumentation on existing FastAPI, `RunService`, and `RuntimeOrchestrator` boundaries.
- The plan does not require database-backed metrics or a second execution path.
- Commit steps are preserved as workflow placeholders even though this workspace is not a git repository.

### Type Consistency

- Observability runtime abstraction is named `MetricsSink`.
- Prometheus-backed implementation is named `PrometheusMetricsSink`.
- Structured logging helpers are `build_log_payload` and `emit_structured_log`.
- Metrics endpoint path is `GET /metrics`.
