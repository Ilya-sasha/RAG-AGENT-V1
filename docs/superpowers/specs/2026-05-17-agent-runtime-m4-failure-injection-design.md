# Agent Runtime M4 Failure Injection Design

**Date:** 2026-05-17

**Status:** Draft for review

## 1. Goal

Add a deterministic failure injection suite for the runtime core so tests can force model and tool failures at specific execution boundaries and verify that the existing runtime still fails, records events, and resumes state consistently.

This phase is not a general chaos platform. It is a controlled test infrastructure layer for explicit failure scenarios.

## 2. Scope

### In Scope

- a dedicated `FaultInjector` abstraction
- deterministic rule-based fault injection for tests
- runtime-node fault points
- model and tool boundary fault points
- integration tests proving runtime failure handling under injected faults

### Out of Scope

- random or probabilistic chaos testing
- production runtime toggles for fault injection
- environment-variable fault control
- persistence-layer and event-publisher fault injection
- approval race and cancel race injection

## 3. Design Principles

- injected faults must be handled exactly like real runtime failures
- production defaults must remain zero-impact through a no-op injector
- tests must configure failures explicitly and deterministically
- fault rules must be simple enough to read directly from the test body
- the abstraction must be reusable for later fault domains without changing the calling pattern

## 4. Architecture

### Core Module

Create:

- `src/agent_runtime/testing/faults.py`

This module owns:

- `FaultPoint`
- `FaultRule`
- `FaultInjector`
- `NoopFaultInjector`
- `RuleBasedFaultInjector`

### Runtime Integration Points

- `src/agent_runtime/api/app.py`
  Accepts an optional `fault_injector` parameter when building the app. Default is `NoopFaultInjector`.

- `src/agent_runtime/runtime/services.py`
  Accepts and passes the injector into the orchestrator and invokes it at runtime-level boundaries.

- `src/agent_runtime/runtime/orchestrator.py`
  Invokes the injector at model and tool boundaries.

## 5. Fault Model

### FaultPoint

The first implementation should define a small explicit enum:

- `RUN_CREATE_BEFORE_DISPATCH`
- `RUN_RESUME_BEFORE_EXECUTE`
- `MODEL_BEFORE_COMPLETE`
- `TOOL_BEFORE_EXECUTE`
- `TOOL_BEFORE_RESUME`

This set is enough to cover the chosen first domain of model and tool failures while leaving room for future extensions.

### FaultRule

Each rule contains:

- `point`
- `times`
- `exception_factory`

Semantics:

- `point` identifies the trigger location
- `times` means the Nth time the point is reached
- `exception_factory` produces the exception that should be raised

The first version does not support predicates, filters, probabilities, or per-run matching.

### FaultInjector Interface

The injector exposes one method:

- `trigger(point: FaultPoint, **context) -> None`

Behavior:

- if no rule matches, return normally
- if a rule matches, raise the produced exception

The context is for observability and future extensibility only. The first phase may pass fields such as:

- `run_id`
- `agent_id`
- `tool_name`

The first phase does not require context-based matching logic.

## 6. Implementations

### NoopFaultInjector

Default production-safe implementation.

Behavior:

- accepts any point
- never raises
- introduces no branching in normal production execution beyond a single call site

### RuleBasedFaultInjector

Test-only deterministic implementation.

Behavior:

- stores a list of ordered `FaultRule` values
- tracks invocation counts per `FaultPoint`
- triggers the first matching rule when the configured count is reached
- stops triggering that rule after its configured count has passed

Matching order is definition order. The first phase does not implement a separate priority mechanism.

## 7. Runtime Data Flow

1. A test constructs `RuleBasedFaultInjector` with explicit rules.
2. The test passes the injector into `create_app(...)`.
3. `create_app(...)` passes the injector into `RunService`.
4. `RunService` passes the injector into `RuntimeOrchestrator`.
5. When execution reaches a fault point, runtime code calls `fault_injector.trigger(...)`.
6. If the injector raises, existing runtime failure handling takes over.
7. The run should still emit the expected terminal `run.failed` event and persist the failure state.

No special injected-fault branch should be added to the failure path. The existing error-handling behavior is the subject under test.

## 8. Test Scenarios

### Scenario 1: Injected Model Failure

At `MODEL_BEFORE_COMPLETE`:

- model completion is never reached successfully
- run transitions to `failed`
- failure event is emitted
- error message contains the injected failure text

### Scenario 2: Injected Tool Execution Failure

At `TOOL_BEFORE_EXECUTE`:

- tool execution never completes
- run transitions to `failed`
- no false tool-completed state is recorded
- failure event is emitted

### Scenario 3: Injected Tool Resume Failure

At `TOOL_BEFORE_RESUME`:

- approval is already resolved as approved
- resume path reaches tool resumption and fails
- run transitions to `failed`
- failure event is emitted

### Scenario 4: Injected Resume Entry Failure

At `RUN_RESUME_BEFORE_EXECUTE`:

- explicit resume attempt fails immediately
- run transitions to `failed`
- failure event is emitted consistently

## 9. Error Handling Expectations

- injected faults must surface as ordinary runtime exceptions
- run failure handling remains centralized in existing orchestration/service logic
- the injector itself should not swallow exceptions
- `NoopFaultInjector` must remain the default everywhere so production behavior is unchanged

## 10. Testing Strategy

### Unit Tests

- rule matching by point
- trigger on configured invocation count
- no-op injector never raises
- rule-based injector stops matching after the configured count has passed

### Integration Tests

- injected model failure causes `run.failed`
- injected tool execution failure causes `run.failed`
- injected tool resume failure causes `run.failed`
- injected resume entry failure causes `run.failed`

### Regression Gate

All existing runtime and observability tests must continue passing with the default no-op injector.

## 11. Implementation Boundaries

This phase should not:

- expose fault injection through API routes
- add environment-driven fault configuration
- add persistence-layer fault injection
- add random failure generation

It should:

- introduce a reusable deterministic fault-injection abstraction
- keep production defaults unchanged
- add focused tests for runtime failure correctness under injected faults
