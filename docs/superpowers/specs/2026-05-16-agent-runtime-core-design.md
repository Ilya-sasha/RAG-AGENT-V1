# Agent Runtime Core Design

**Date:** 2026-05-16

**Status:** Draft for review

## 1. Goal

Build an enterprise-oriented, API-first agent runtime core that supports:

- multi-agent orchestration with a `Supervisor + Worker` model
- streaming runtime events over API
- controlled API-based tool execution
- full checkpoint-based resumability
- built-in human approval checkpoints
- logical multi-tenancy
- provider-agnostic model integration
- private or VPC deployment

The runtime is the execution kernel, not the full platform. It is designed to become the foundation for later memory, RAG, governance, and product-layer capabilities.

## 2. Scope

### In Scope for v1

- run lifecycle management: create, query, resume, cancel
- supervisor and predefined worker execution model
- structured streaming event output using SSE
- API-only tool gateway with schema validation and policy checks
- event store + checkpoint store + relational read models
- crash recovery and resumable execution
- approval-required execution states
- tenant-scoped runtime configuration and policy controls
- provider-agnostic model client abstraction
- baseline observability and auditability

### Out of Scope for v1

- RAG and enterprise knowledge retrieval
- long-term memory and user memory
- peer-to-peer multi-agent collaboration
- dynamic worker generation at runtime
- shell, code execution, or unrestricted tools
- visual chat UI or assistant frontend
- automatic model routing by task or cost
- hard physical tenant isolation
- workflow designer or graph studio

## 3. Key Decisions

### Business and Delivery Shape

- project type: general agent platform
- first sub-project: agent runtime core
- delivery shape: API-first headless runtime
- deployment target: enterprise private or VPC deployment

### Technical Stack

- primary language: Python
- web framework: FastAPI
- execution mode: synchronous request with streaming runtime events
- orchestration model: multi-agent with `Supervisor + Worker`
- tool boundary: controlled API tools only
- model strategy: provider-agnostic abstraction layer
- tenancy model: logical multi-tenancy
- state durability: full resumability with checkpoint and recovery
- approval model: built-in human-in-the-loop approval points
- worker provisioning: predefined worker types

## 4. Architecture Overview

The runtime core is an event-driven execution system. Every state transition is represented as a recorded runtime fact, and critical execution boundaries are checkpointed so that supervisor and worker agents can resume after process or service interruption.

### Core Components

1. `Runtime API`
   Exposes run lifecycle, event streaming, approval actions, tool registry management, and tenant policy endpoints.

2. `Orchestrator`
   Drives execution through scheduled agent ticks. Decides when to invoke the supervisor, dispatch workers, merge results, pause for approval, or resume from checkpoints.

3. `Agent Engine`
   Encapsulates the reasoning loop for both supervisor and worker agents. Handles prompt assembly, model invocation, structured parsing, and step termination decisions.

4. `Tool Gateway`
   Central gateway for tool registration, schema validation, policy enforcement, timeout and retry behavior, and audit capture. v1 supports only controlled API and SDK-backed tools.

5. `State Store`
   Persists event history, query models, and checkpoints. Supports recovery, replay, audits, and run inspection.

6. `Streaming/Event Bus`
   Emits structured runtime events such as planning, dispatch, tool execution, approval requests, checkpoint creation, completion, and failure.

### Architectural Principles

- model execution is separated from tool execution
- agents do not directly call databases or external APIs
- all cross-boundary actions require durable state writes
- multi-agent behavior is explicit in the data model, not inferred from message text
- recovery is state-machine based, not heuristic

## 5. Data Model

The runtime must be built around execution objects, not around chat messages.

### Primary Entities

- `Tenant`
  Holds tenant identity, quotas, model configuration, tool allowlists, approval policies, and audit policy settings.

- `Session`
  Groups related runs for business-level continuity. It is not the lowest-level recovery unit.

- `Run`
  Represents a single top-level execution request. Owns global objective, input payload, result payload, and terminal state.

- `AgentInstance`
  Represents a concrete supervisor or worker execution instance. Holds role, parent-child relationship, bound tool set, status, and resume metadata.

- `Task`
  Represents work delegated by the supervisor to a worker. Contains objective, constraints, context slice, and expected output contract.

- `Step`
  Represents an atomic execution advance, such as reasoning, tool selection, worker dispatch, approval wait, or completion.

- `ToolInvocation`
  Represents a single tool call, including validated parameters, retry count, status, timing, idempotency key, and normalized response.

- `ApprovalRequest`
  Represents an execution pause that requires a human decision before continuation.

- `Checkpoint`
  Represents the persisted recovery snapshot for an agent or run at a critical execution boundary.

- `Event`
  Represents the immutable fact log that records lifecycle transitions and execution outcomes.

### Persistence Strategy

Use three storage views:

- `Event Store`
  Source of truth for immutable execution facts.

- `Relational Read Model`
  Query-optimized tables for API reads, dashboards, and operational inspection.

- `Checkpoint Store`
  Fast access to latest recoverable state snapshots.

This separation keeps replay and audit correctness independent from query performance.

## 6. State Machines

### Run States

- `created`
- `running`
- `waiting_for_approval`
- `paused`
- `failed`
- `completed`
- `cancelled`

### AgentInstance States

- `created`
- `ready`
- `reasoning`
- `dispatching`
- `waiting_on_workers`
- `waiting_on_tool`
- `waiting_for_approval`
- `checkpointing`
- `resuming`
- `completed`
- `failed`
- `cancelled`

### Supervisor State Behavior

The supervisor is responsible for:

- interpreting the top-level goal
- planning and decomposition
- selecting predefined worker types
- dispatching tasks
- merging worker outputs into structured observations
- requesting approval when policy requires it
- deciding completion, retry, fallback, or failure

The supervisor may call tools directly only when allowed by policy, but it does not execute tools internally.

### Worker State Behavior

Workers are narrower in responsibility:

- receive a task with bounded context
- reason over the task
- call approved tools through the gateway
- produce structured output and evidence
- return results to the supervisor

Workers do not coordinate directly with each other in v1.

## 7. Execution Flow

Execution is driven by schedulable agent ticks rather than by a single long-lived HTTP request thread.

### Main Flow

1. `Create Run`
   The API creates a run, session link, initial context snapshot, and supervisor instance, then records `run_created`.

2. `Supervisor Tick`
   The orchestrator runs one supervisor tick. The tick may:
   - produce a final answer
   - dispatch worker tasks
   - request a tool call
   - request human approval
   - fail with a runtime or policy error

3. `Worker Execution`
   Each delegated task becomes a worker `AgentInstance` with its own bounded context and lifecycle.

4. `Tool Execution`
   Tool calls are sent to the `Tool Gateway`, which performs validation, authorization, retries, timing, and audit capture.

5. `Checkpointing`
   The runtime persists checkpoints before and after critical boundaries.

6. `Merge and Continue`
   Worker results are merged into supervisor observations, then the next supervisor tick is scheduled.

### Mandatory Checkpoint Boundaries

- before model invocation
- after model invocation result is accepted
- after worker dispatch is recorded
- after tool invocation submission is recorded
- before entering approval wait
- before final completion

## 8. Recovery Model

v1 requires full resumability, not log-only postmortem analysis.

### Recovery Layers

- `Run-level resume`
  Rebuild scheduling state for non-terminal runs after restart.

- `Agent-level resume`
  Restore supervisor or worker execution from the latest valid checkpoint.

- `Boundary-level idempotency`
  Prevent duplicate side effects when recovering tool calls, approvals, or worker completions.

### Recovery Rules

- if interruption occurs before a model call, resume from the last checkpoint and call the model
- if interruption occurs after a model call but before durable acceptance of the result, treat the call as uncertain and apply retry policy
- if interruption occurs after tool submission, resolve by idempotency key and stored invocation status
- if interruption occurs during approval wait, restore the run to `waiting_for_approval`
- if interruption occurs after worker completion but before supervisor merge, retain worker result events and rerun only the merge step

### Reliability Requirement

No execution transition may advance past a critical boundary unless the related event and checkpoint are durably stored.

## 9. Multi-Agent Model

v1 supports one supervisor and multiple predefined worker types.

### Initial Worker Profiles

The exact profile names may change during implementation, but the first version should support at least:

- `researcher`
  Gathers evidence through approved tools and returns summarized findings.

- `tool-runner`
  Executes operational or business API tools within a constrained instruction envelope.

More worker types can be added later through controlled profile registration.

### Collaboration Contract

- supervisor creates tasks
- worker executes task
- worker returns structured result
- supervisor merges result and decides next step

There is no worker-to-worker direct messaging in v1.

## 10. Tool Execution Model

The tool boundary is intentionally strict.

### v1 Rules

- only API and SDK-backed tools are allowed
- each tool must define a strict input schema
- each tool is registered per runtime control plane
- each tenant is assigned a tool allowlist
- each invocation must be auditable
- retry behavior is owned by the gateway, not by agent prompt logic

### Tool Gateway Responsibilities

- input schema validation
- policy checks
- timeout enforcement
- retry handling
- idempotency tracking
- response normalization
- audit event emission

## 11. Approval Model

Approval is a first-class runtime state, not an exception case.

### Approval Triggers

Approval may be required because of:

- tool sensitivity
- tenant policy
- action category
- operational risk threshold

### Approval Behavior

- the runtime emits `approval.requested`
- the run and related agent move to `waiting_for_approval`
- an approver approves or rejects through API
- approval outcome is recorded as durable events
- approved runs resume from the checkpoint before the approval gate
- rejected runs fail or terminate according to policy

## 12. API Design

The public API exposes execution semantics rather than prompt details.

### Run API

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `POST /v1/runs/{run_id}/resume`
- `POST /v1/runs/{run_id}/cancel`

### Stream API

- `GET /v1/runs/{run_id}/events`

Use Server-Sent Events for v1 because it is simple to consume, easier to operate in enterprise environments, and well suited for runtime event feeds.

### Approval API

- `GET /v1/approvals/{approval_id}`
- `POST /v1/approvals/{approval_id}/approve`
- `POST /v1/approvals/{approval_id}/reject`

### Tool Registry API

- `POST /v1/tools`
- `GET /v1/tools`
- `GET /v1/tools/{tool_name}`

### Tenant and Policy API

- `POST /v1/tenants`
- `GET /v1/tenants/{tenant_id}`
- `PUT /v1/tenants/{tenant_id}/policies`

### Example Run Creation Payload

```json
{
  "tenant_id": "acme-prod",
  "session_id": "sess_123",
  "input": {
    "message": "Analyze this incident and propose next actions"
  },
  "runtime_config": {
    "supervisor_profile": "default-supervisor",
    "worker_profiles": [
      "researcher",
      "tool-runner"
    ],
    "stream": true,
    "resume_mode": "checkpointed"
  },
  "policy_context": {
    "user_id": "u_42",
    "roles": [
      "ops_admin"
    ]
  }
}
```

## 13. Event Model

The stream and the audit trail should use the same event vocabulary.

### Minimum Runtime Events

- `run.created`
- `agent.started`
- `agent.reasoned`
- `task.dispatched`
- `tool.called`
- `tool.completed`
- `approval.requested`
- `approval.resolved`
- `checkpoint.created`
- `agent.completed`
- `run.completed`
- `run.failed`

Events must include:

- event id
- tenant id
- run id
- agent id when applicable
- event type
- timestamp
- status payload
- trace id
- cost or latency metadata when available

## 14. Codebase Module Boundaries

The implementation should follow domain boundaries rather than generic MVC layering.

### Recommended Modules

- `api`
  FastAPI routes, request and response schemas, SSE adapters

- `runtime`
  Orchestrator, scheduling, lifecycle control, recovery coordinator

- `agents`
  Supervisor engine, worker engine, agent profiles, prompt assembly

- `tools`
  Registry, gateway, executors, policy enforcement, result normalization

- `models`
  Provider-agnostic model interface, provider adapters, structured output parsing

- `state`
  Event store, read models, checkpoint persistence, concurrency and locking controls

- `approvals`
  Approval policies, state transitions, API handlers

- `tenancy`
  Tenant configuration, quota enforcement, policy loading

- `observability`
  Logging, metrics, tracing, audit emitters

### Hard Boundary Rule

The `agent engine` must not:

- execute tools directly
- write to the database directly
- call external systems except through approved model adapters

This keeps orchestration, persistence, and side effects explicit and testable.

## 15. Non-Functional Requirements

### Reliability

- run, agent, and tool invocations require idempotency keys
- resume may be triggered repeatedly without duplicating external effects
- invalid state transitions must be rejected deterministically

### Observability

- every run, agent, task, and tool call must emit correlated logs
- metrics should include status counts, latency, retry counts, and recovery counts
- traces must preserve tenant and run context

### Security

- tenant-scoped tool allowlists
- isolated model credentials by tenant or deployment policy
- approval policy hooks for sensitive actions
- audit records with sensitive data redaction rules

### Operability

- operators must be able to inspect blocked runs
- operators must be able to inspect pending approvals
- operators must be able to inspect latest checkpoint per run
- operators must be able to identify stuck or flapping tasks

### Extensibility

- tool adapters are pluggable under controlled registration
- worker profiles are pluggable under controlled registration
- model providers are swappable behind a stable interface

v1 should avoid arbitrary runtime code loading.

## 16. Error Taxonomy

Errors should be grouped by system boundary.

- `ModelError`
  model timeout, malformed structured output, provider failure

- `ToolError`
  schema validation failure, tool timeout, upstream tool failure, authorization failure

- `PolicyError`
  tenant policy denial, approval rejection, quota violation

- `RuntimeError`
  checkpoint failure, illegal state transition, recovery conflict, scheduling error

Every surfaced error should include:

- `error_code`
- `retryable`
- `scope`
- `related_run_id`
- `related_agent_id`

## 17. Testing Strategy

v1 requires test coverage across behavior, recovery, and contracts.

### Required Test Layers

- `Unit tests`
  state transitions, policy decisions, tool schema validation, event construction

- `Integration tests`
  run creation, worker dispatch, approval pause and resume, checkpoint recovery

- `Failure injection tests`
  crash during model boundary, tool boundary, approval boundary, and merge boundary

- `Contract tests`
  provider adapters, tool adapters, event schema compatibility, SSE output format

### Acceptance Criteria

The runtime is not considered production-ready unless resume behavior is verified under simulated interruption scenarios.

## 18. Delivery Milestones

### M1: Single-Agent Resilient Core

- one supervisor only
- event stream
- checkpointing
- durable run lifecycle
- crash recovery baseline

### M2: Multi-Agent Orchestration

- task dispatch
- worker lifecycle
- worker result merge
- resume across supervisor and workers

### M3: Tool Governance and Approval

- tool gateway
- tenant policy enforcement
- approval state machine
- audit coverage

### M4: Production Hardening

- observability completion
- failure injection suite
- performance baseline
- deployment and operations documentation

## 19. Recommendation

The recommended implementation path is to treat this runtime as an event-driven execution kernel, not as a chatbot server. That keeps multi-agent orchestration, resumability, approvals, and governance aligned from the start instead of being retrofitted later.

The first implementation plan should focus on `M1` and `M2` before introducing broader platform concerns such as memory systems, knowledge retrieval, or workflow design surfaces.
