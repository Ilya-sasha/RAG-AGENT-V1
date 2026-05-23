# Agent Runtime M4 Performance Baseline Design

**Date:** 2026-05-17

**Status:** Draft for review

## 1. Goal

Add a first-generation performance baseline for the runtime core so the project has a repeatable way to:

- measure latency and throughput for the most important API/runtime paths
- save baseline samples in the repository for future comparison
- detect obvious regressions through a lightweight pytest gate

This phase is not a full load-testing program and does not define production sizing guarantees. It establishes a stable local regression baseline for the current runtime implementation.

## 2. Scope

### In Scope

- a dedicated benchmark module for core API/runtime scenarios
- repository-stored JSON baseline samples
- pytest-based regression checks against the saved baseline
- documentation for generating, updating, and interpreting the baseline

### Out of Scope

- multi-agent performance benchmarking
- real HTTP server benchmarking through `uvicorn`
- external load-testing tools such as `k6`, `Locust`, or `wrk`
- production capacity planning or deployment sizing claims
- absolute latency threshold enforcement in this phase

## 3. Design Principles

- the first baseline must be stable and repeatable on a local development machine
- benchmark collection and regression assertion must remain separate concerns
- benchmark scenarios must map directly to current public API/runtime behavior
- baseline comparison should tolerate normal local-machine noise and only fail on clear regressions
- the implementation must reuse the existing FastAPI app and runtime wiring instead of creating a benchmark-only execution path

## 4. Architecture

### Benchmark Strategy

Use the existing `create_app(...)` entrypoint together with `httpx.AsyncClient` and `ASGITransport`.

This phase intentionally benchmarks the runtime in-process rather than through a real listening HTTP server. The goal is to reduce network and scheduler noise and make the first baseline more stable and easier to reproduce.

### Proposed Files

Create:

- `tests/perf/__init__.py`
- `tests/perf/benchmarks/__init__.py`
- `tests/perf/benchmarks/core_api.py`
- `tests/perf/baselines/core_api_baseline.json`
- `tests/perf/test_core_api_regression.py`
- `docs/performance-baseline.md`

The benchmark module owns scenario execution and result aggregation. The pytest regression test owns baseline loading and pass/fail assertions. The documentation explains the workflow and expected interpretation.

## 5. Scenario Set

The first-generation baseline covers only the single-run core runtime path.

### Scenario 1: `run_create_complete`

Flow:

1. create a run through `POST /v1/runs`
2. use a scripted supervisor that finishes directly
3. poll `GET /v1/runs/{run_id}` until the run reaches `completed`
4. measure end-to-end time from create request start until the completed state is observed

### Scenario 2: `run_create_wait_for_approval`

Flow:

1. create a run through `POST /v1/runs`
2. use a scripted supervisor that selects a tool requiring approval
3. poll `GET /v1/runs/{run_id}` until the run reaches `waiting_for_approval`
4. measure end-to-end time from create request start until the waiting state is observed

### Scenario 3: `approval_approve_resume_complete`

Flow:

1. create a run that reaches `waiting_for_approval`
2. resolve the approval through `POST /v1/approvals/{approval_id}/approve`
3. rely on the current API behavior to resume the run to completion before the approval response returns
4. measure the approval-and-resume completion path as one scenario

### Scenario 4: `metrics_scrape`

Flow:

1. create an initialized app
2. issue `GET /metrics`
3. measure scrape latency for the in-memory Prometheus export endpoint

## 6. Benchmark Data Model

The baseline file must store only stable, comparison-oriented fields.

Each scenario record stores:

- `scenario`
- `iterations`
- `warmup_iterations`
- `latency_ms_p50`
- `latency_ms_p95`
- `latency_ms_max`
- `throughput_ops_per_sec`
- `degradation_tolerance_ratio`

### Baseline File

Use a single JSON file for the first-generation baseline:

- `tests/perf/baselines/core_api_baseline.json`

The file should contain:

- metadata describing how the sample was generated
- one record per scenario

Recommended metadata fields:

- `baseline_name`
- `generated_at`
- `python_version`
- `scenario_count`

The first phase does not need host-specific metadata such as CPU model or memory size because this is a repository-local baseline, not a fleet benchmarking system.

## 7. Execution Flow

### Benchmark Collection

For each scenario:

1. construct a fresh temporary database path
2. construct a fresh app instance through `create_app(...)`
3. configure a deterministic model script and tool setup for the scenario
4. run a small warmup loop
5. run a fixed number of measured iterations
6. record per-iteration duration with `time.perf_counter()`
7. derive percentile and throughput values

### Isolation Rules

- each scenario uses a fresh app and fresh database
- the benchmark module must not reuse prior run state across scenarios
- each scenario should use deterministic scripted model decisions and test-only tool executors

These rules keep the sample easy to compare and reduce hidden interaction effects.

## 8. Regression Rules

This phase uses relative regression protection, not absolute thresholds.

### Failure Conditions

The pytest gate fails when either condition is true for any scenario:

- current `latency_ms_p95` is more than `50%` worse than the saved baseline
- current `throughput_ops_per_sec` is more than `50%` worse than the saved baseline

### Missing Baseline Behavior

If the baseline file is missing, the regression test must fail explicitly with a clear message that the baseline sample has not been generated.

The test must not silently skip or auto-create the baseline during normal regression execution.

## 9. Testing Strategy

### Unit-Level Coverage

The first phase does not need a separate low-level microbenchmark unit suite. The benchmark module itself is the primary artifact under test.

### Regression Coverage

Add a pytest file that:

- loads the saved baseline JSON
- re-runs the benchmark scenarios
- compares current results to baseline values
- emits a readable failure message identifying the regressed scenario and metric

### Verification Scope

The new performance baseline must not break the existing runtime suite. All existing tests must continue passing after the benchmark and regression files are added.

## 10. Documentation

Add a short operating document at `docs/performance-baseline.md` that explains:

- what the first-generation baseline covers
- how to generate or refresh the JSON baseline
- how to run the regression test
- how to interpret a regression failure
- what is intentionally deferred to a later phase

## 11. Deferred Follow-Up

The following items are explicitly deferred beyond this phase:

- multi-agent benchmark scenarios
- mixed regression strategy using both relative degradation and absolute limits
- real HTTP server benchmark mode using a live `uvicorn` process
- deeper repository or persistence microbenchmarks

The next performance iteration should prioritize multi-agent scenarios after the first-generation runtime roadmap is otherwise complete.

## 12. Implementation Boundaries

This phase should not:

- alter runtime business behavior to optimize benchmark outcomes
- add benchmark-only code paths in production modules
- change API semantics for approval or resume handling
- claim enterprise production capacity or SLO targets

It should:

- provide a deterministic benchmark harness for the current core runtime
- store a stable first-generation baseline in the repository
- add a pragmatic regression gate that catches obvious slowdowns without being too sensitive to local noise
