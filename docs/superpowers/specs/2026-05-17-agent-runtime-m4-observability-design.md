# Agent Runtime M4 Observability Design

**Date:** 2026-05-17

**Status:** Draft for review

## 1. Goal

Add production-oriented observability to the existing runtime core so operators can:

- inspect request, run, and agent activity through structured logs
- scrape Prometheus-compatible metrics from a standard `HTTP /metrics` endpoint
- diagnose runtime, approval, and tool-execution issues without querying internal tables directly

This phase does not implement distributed tracing. Tracing is explicitly deferred to a later phase after the broader runtime roadmap is completed.

## 2. Scope

### In Scope

- structured logging for request-level, run-level, and agent-level events
- Prometheus text exposition at `GET /metrics`
- a thin observability abstraction layer so business code does not depend directly on metrics library details
- request context propagation for `request_id` and correlation into run and agent logs
- runtime metrics for HTTP, run lifecycle, agent decisions, tool calls, and approval resolutions
- tests covering metrics export, metric increments, and regression safety

### Out of Scope

- tracing implementation, span export, or OpenTelemetry SDK wiring
- log shipping pipelines such as ELK, Loki, or cloud vendor integrations
- dashboards, alerts, or Grafana assets
- high-cardinality per-run or per-agent metrics labels
- repository-level exhaustive debug logs

## 3. Design Principles

- observability must not create a second orchestration path
- observability failures must never fail a run or block an API response
- logs may carry high-cardinality identifiers such as `run_id` and `agent_id`
- metrics must avoid high-cardinality labels and stay Prometheus-safe
- instrumentation should attach to existing runtime boundaries instead of scattering ad hoc counters across the codebase
- the code should reserve a clean extension point for future tracing

## 4. Architecture

### Observability Layer

Create a dedicated `observability` package with focused responsibilities:

1. `src/agent_runtime/observability/context.py`
   Defines request-scoped context helpers and correlation field propagation. The minimum context set is:
   - `request_id`
   - `tenant_id`
   - `run_id`
   - `agent_id`

2. `src/agent_runtime/observability/logging.py`
   Defines a small structured logging adapter and helper functions for stable field emission. This layer owns:
   - logger creation
   - JSON-friendly payload construction
   - best-effort emission wrappers so logging failures do not propagate

3. `src/agent_runtime/observability/metrics.py`
   Defines a `MetricsSink` abstraction and a Prometheus-backed implementation. Business code depends on the abstraction only.

4. `src/agent_runtime/api/routes/metrics.py`
   Exposes `GET /metrics` and returns Prometheus text format from the configured registry.

### Integration Points

- `src/agent_runtime/api/app.py`
  Initializes observability services, installs request middleware, and includes the metrics router.

- `src/agent_runtime/runtime/services.py`
  Emits structured logs and lifecycle metrics for:
  - create run
  - resume run
  - cancel run
  - approval approve
  - approval reject
  - run execution failure paths

- `src/agent_runtime/runtime/orchestrator.py`
  Emits structured logs and metrics for:
  - run started
  - agent started
  - agent decision kind
  - task dispatch
  - tool call start and completion
  - waiting for approval
  - agent completion
  - run completion

- `src/agent_runtime/state/event_stream.py`
  Stays mostly unchanged. It is an audit/event transport component, not the primary observability boundary.

## 5. Logging Design

### Log Shape

Logs should be structured and machine-parseable. Each emitted record should use stable keys such as:

- `message`
- `component`
- `request_id`
- `tenant_id`
- `run_id`
- `agent_id`
- `event_type`
- `status`
- `decision_kind`
- `tool_name`
- `approval_id`
- `duration_ms`
- `error`

### Logging Coverage

#### Request-Level Logs

Emit one start and one finish record per HTTP request. Include:

- `request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`

#### Run-Level Logs

Emit records when the runtime:

- creates a run
- resumes a run
- cancels a run
- transitions into waiting for approval
- resolves an approval
- completes a run
- fails a run

#### Agent-Level Logs

Emit records when an agent:

- starts reasoning
- produces a decision
- dispatches a worker
- calls a tool
- resumes after approval
- completes
- fails indirectly as part of run failure

### Error Handling

All logging must be best effort. If logging serialization or handler emission fails, the runtime continues normally. The fallback behavior is:

- swallow the logging exception
- avoid recursive logging
- preserve business control flow

## 6. Metrics Design

### Metrics Backend

Use a `MetricsSink` abstraction with a Prometheus-backed implementation for the current phase. This keeps the main runtime decoupled from the specific library while still using the standard `prometheus_client` exporter underneath.

### Export Endpoint

Expose:

- `GET /metrics`

The endpoint must:

- return valid Prometheus text exposition
- be available even when no runs have executed
- avoid database access during scrape

### Metric Set

The first metric set is intentionally small and operationally meaningful:

- `http_requests_total`
- `http_request_duration_seconds`
- `runtime_runs_created_total`
- `runtime_runs_completed_total`
- `runtime_runs_failed_total`
- `runtime_runs_waiting_for_approval_total`
- `runtime_agent_decisions_total`
- `runtime_tool_calls_total`
- `runtime_tool_call_duration_seconds`
- `runtime_approval_resolutions_total`

### Label Strategy

Allowed low-cardinality labels:

- HTTP: `method`, `route`, `status_code`
- run: `status`
- decision: `kind`
- tool: `tool_name`, `status`
- approval: `status`

Explicitly forbidden metric labels for this phase:

- `run_id`
- `agent_id`
- `request_id`
- free-form error text

These identifiers remain in logs only.

## 7. Data Flow

1. A request enters FastAPI middleware.
2. Middleware assigns or propagates `request_id`.
3. Middleware records request-start log context.
4. Request handling code calls `RunService` or approval APIs.
5. `RunService` emits lifecycle logs and metrics.
6. `RuntimeOrchestrator` emits agent, tool, and approval-wait logs and metrics.
7. Middleware records request completion metrics and logs.
8. Prometheus scrapes `/metrics` from in-memory registry state.

The existing `RuntimeEvent` table remains the source of auditable execution facts. Logs and metrics supplement operations and diagnostics; they do not replace persisted events.

## 8. Testing Strategy

### Unit Tests

- `MetricsSink` abstraction behavior
- Prometheus-backed exporter text output
- structured log payload helper behavior

### Integration Tests

- `GET /metrics` returns success and valid Prometheus-style text
- creating and completing a run increments run metrics
- approval wait and resolution update approval metrics
- tool execution updates tool metrics
- request middleware increments request counters and request duration metrics

### Regression Gate

All existing runtime tests must continue passing after instrumentation is added.

## 9. Implementation Boundaries

This phase should not:

- redesign the runtime event model
- introduce asynchronous background exporters
- add log configuration files or environment-driven configuration matrixes
- add tracing shims that are not used

It should:

- create a stable `observability` boundary
- instrument the existing runtime and API flow conservatively
- keep the first implementation small enough to verify in one dedicated M4 plan

## 10. Deferred Tracing Plan

Tracing is deferred, but the current design should make it easy to add later by:

- preserving a dedicated observability package
- keeping correlation context explicit
- avoiding direct `prometheus_client` calls in business logic
- not coupling log payload shape to metrics internals

When tracing is scheduled later, it should be planned as a separate sub-project rather than folded into this implementation.
