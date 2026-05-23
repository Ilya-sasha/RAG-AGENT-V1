# Agent Runtime M4 Performance Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-generation performance baseline harness for the core runtime API so the repository can store local baseline samples and catch obvious regressions through pytest.

**Architecture:** This phase keeps all implementation inside `tests/perf/` and `docs/` so runtime business behavior stays unchanged. A benchmark module runs the current FastAPI app in-process through `httpx.ASGITransport`, writes a JSON baseline for four core scenarios, and a regression test compares current results to the saved baseline using relative degradation thresholds.

**Tech Stack:** Python 3.11+, FastAPI, httpx, pytest, pytest-asyncio, existing scripted model client, existing tool registry and approval flow

---

## File Structure

### Create

- `tests/perf/__init__.py`
  Marks the performance test package so the benchmark module can be executed with `python -m`.
- `tests/perf/benchmarks/__init__.py`
  Marks the benchmark package.
- `tests/perf/benchmarks/core_api.py`
  Core benchmark harness, scenario setup helpers, JSON serialization helpers, and module entrypoint for writing baseline files.
- `tests/perf/baselines/core_api_baseline.json`
  Repository-stored first-generation baseline sample.
- `tests/perf/test_core_api_benchmark.py`
  Smoke test that verifies the harness returns the expected scenarios and metrics shape.
- `tests/perf/test_core_api_regression.py`
  Regression guard that loads the baseline file, reruns the harness, and fails on excessive relative degradation.
- `docs/performance-baseline.md`
  Operator-facing instructions for generating, refreshing, and interpreting the baseline.

### Modify

- `docs/superpowers/specs/2026-05-17-agent-runtime-m4-performance-baseline-design.md`
  Keep the approved spec aligned with current API semantics by describing polling-based completion and waiting-state observation.

## Task 1: Build The Core API Benchmark Harness

**Files:**
- Create: `tests/perf/__init__.py`
- Create: `tests/perf/benchmarks/__init__.py`
- Create: `tests/perf/benchmarks/core_api.py`
- Create: `tests/perf/test_core_api_benchmark.py`

- [ ] **Step 1: Write the failing harness smoke test**

```python
# tests/perf/test_core_api_benchmark.py
import pytest

from tests.perf.benchmarks.core_api import run_core_api_benchmarks


@pytest.mark.asyncio
async def test_run_core_api_benchmarks_returns_expected_scenarios(tmp_path) -> None:
    report = await run_core_api_benchmarks(
        tmp_path=tmp_path,
        iterations=1,
        warmup_iterations=0,
    )

    scenarios = {item["scenario"] for item in report["scenarios"]}
    assert scenarios == {
        "run_create_complete",
        "run_create_wait_for_approval",
        "approval_approve_resume_complete",
        "metrics_scrape",
    }

    for item in report["scenarios"]:
        assert item["latency_ms_p50"] >= 0
        assert item["latency_ms_p95"] >= 0
        assert item["latency_ms_max"] >= 0
        assert item["throughput_ops_per_sec"] > 0
        assert item["degradation_tolerance_ratio"] == 0.5
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_benchmark.py -v`
Expected: FAIL with `ModuleNotFoundError` for `tests.perf.benchmarks.core_api`

- [ ] **Step 3: Add the benchmark package markers**

```python
# tests/perf/__init__.py
"""Performance benchmark test package."""
```

```python
# tests/perf/benchmarks/__init__.py
"""Benchmark harness package for runtime performance baselines."""
```

- [ ] **Step 4: Implement the core harness with deterministic scenario helpers**

```python
# tests/perf/benchmarks/core_api.py
from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles

from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.domain.models import TenantPolicyRecord, ToolDefinitionRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.tools.base import ToolExecutionRequest, ToolExecutionResult, ToolExecutor
from agent_runtime.tools.registry import ToolRegistry

BASELINE_PATH = Path(__file__).resolve().parents[1] / "baselines" / "core_api_baseline.json"
DEFAULT_ITERATIONS = 5
DEFAULT_WARMUP_ITERATIONS = 1
DEFAULT_DEGRADATION_TOLERANCE_RATIO = 0.5


class StaticExecutor(ToolExecutor):
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        del request
        return ToolExecutionResult(output={"status": "ok"})


@dataclass(slots=True)
class ScenarioMetrics:
    scenario: str
    iterations: int
    warmup_iterations: int
    latency_ms_p50: float
    latency_ms_p95: float
    latency_ms_max: float
    throughput_ops_per_sec: float
    degradation_tolerance_ratio: float


async def run_core_api_benchmarks(
    *,
    tmp_path: Path,
    iterations: int = DEFAULT_ITERATIONS,
    warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS,
    degradation_tolerance_ratio: float = DEFAULT_DEGRADATION_TOLERANCE_RATIO,
) -> dict[str, object]:
    scenarios = [
        ("run_create_complete", _measure_run_create_complete),
        ("run_create_wait_for_approval", _measure_run_create_wait_for_approval),
        ("approval_approve_resume_complete", _measure_approval_approve_resume_complete),
        ("metrics_scrape", _measure_metrics_scrape),
    ]
    results: list[dict[str, object]] = []
    for name, runner in scenarios:
        metrics = await _run_scenario(
            scenario=name,
            runner=runner,
            tmp_path=tmp_path,
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            degradation_tolerance_ratio=degradation_tolerance_ratio,
        )
        results.append(asdict(metrics))
    return {
        "baseline_name": "core_api",
        "generated_at": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        "scenario_count": len(results),
        "scenarios": results,
    }


async def write_core_api_baseline(
    *,
    output_path: Path,
    tmp_path: Path,
    iterations: int = DEFAULT_ITERATIONS,
    warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS,
) -> dict[str, object]:
    report = await run_core_api_benchmarks(
        tmp_path=tmp_path,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


async def _run_scenario(
    *,
    scenario: str,
    runner: Callable[[Path], Awaitable[float]],
    tmp_path: Path,
    iterations: int,
    warmup_iterations: int,
    degradation_tolerance_ratio: float,
) -> ScenarioMetrics:
    scenario_tmp = tmp_path / scenario
    scenario_tmp.mkdir(parents=True, exist_ok=True)

    for index in range(warmup_iterations):
        await runner(scenario_tmp / f"warmup-{index}")

    latencies: list[float] = []
    started = time.perf_counter()
    for index in range(iterations):
        latency_ms = await runner(scenario_tmp / f"iteration-{index}")
        latencies.append(latency_ms)
    elapsed = time.perf_counter() - started

    return ScenarioMetrics(
        scenario=scenario,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        latency_ms_p50=_percentile_ms(latencies, 50),
        latency_ms_p95=_percentile_ms(latencies, 95),
        latency_ms_max=max(latencies),
        throughput_ops_per_sec=iterations / elapsed if elapsed > 0 else math.inf,
        degradation_tolerance_ratio=degradation_tolerance_ratio,
    )


def _percentile_ms(values: list[float], percentile: int) -> float:
    if len(values) == 1:
        return values[0]
    bucket = quantiles(values, n=100, method="inclusive")
    return bucket[percentile - 1]
```

- [ ] **Step 5: Implement the scenario runners and cleanup behavior**

```python
# tests/perf/benchmarks/core_api.py
async def _measure_run_create_complete(workdir: Path) -> float:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{workdir / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="benchmark result",
                    )
                ]
            }
        ),
    )
    return await _measure_create_to_status(app, target_status="completed")


async def _measure_run_create_wait_for_approval(workdir: Path) -> float:
    app = await _build_approval_app(workdir, finish_after_tool=False)
    latency_ms, approval_id = await _measure_create_to_waiting(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.post(f"/v1/approvals/{approval_id}/reject", json={"resolution_note": "benchmark cleanup"})
    await app.state.run_service.shutdown()
    return latency_ms


async def _measure_approval_approve_resume_complete(workdir: Path) -> float:
    app = await _build_approval_app(workdir, finish_after_tool=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        _, approval_id = await _create_waiting_run(client, app)
        started = time.perf_counter()
        response = await client.post(
            f"/v1/approvals/{approval_id}/approve",
            json={"resolution_note": "benchmark approval"},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 200
    await app.state.run_service.shutdown()
    return elapsed_ms


async def _measure_metrics_scrape(workdir: Path) -> float:
    app = create_app(db_url=f"sqlite+aiosqlite:///{workdir / 'runtime.db'}")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        started = time.perf_counter()
        response = await client.get("/metrics")
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 200
    await app.state.run_service.shutdown()
    return elapsed_ms


async def _measure_create_to_status(app, *, target_status: str) -> float:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        started = time.perf_counter()
        response = await client.post("/v1/runs", json={"tenant_id": "tenant-a", "objective": "benchmark"})
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        await _wait_for_run_status(client, run_id, target_status)
        elapsed_ms = (time.perf_counter() - started) * 1000
    await app.state.run_service.shutdown()
    return elapsed_ms


async def _measure_create_to_waiting(app) -> tuple[float, str]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        started = time.perf_counter()
        run_id, approval_id = await _create_waiting_run(client, app)
        await _wait_for_run_status(client, run_id, "waiting_for_approval")
        elapsed_ms = (time.perf_counter() - started) * 1000
    return elapsed_ms, approval_id
```

- [ ] **Step 6: Add approval setup helpers and module entrypoint**

```python
# tests/perf/benchmarks/core_api.py
async def _build_approval_app(workdir: Path, *, finish_after_tool: bool):
    registry = ToolRegistry()
    registry.register("payment-api", StaticExecutor())
    scripts = [
        ModelDecision(
            kind=DecisionKind.CALL_TOOL,
            summary="call payment tool",
            tool_name="payment-api",
            tool_arguments={"amount": 10},
        )
    ]
    if finish_after_tool:
        scripts.append(
            ModelDecision(
                kind=DecisionKind.FINISH,
                summary="done",
                final_output="payment submitted",
            )
        )
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{workdir / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": scripts}),
        tool_registry=registry,
    )
    await app.state.ensure_initialized()
    repository = app.state.run_service._repository
    await repository.upsert_tenant_policy(
        TenantPolicyRecord(
            tenant_id="tenant-a",
            allowed_tools=["payment-api"],
            approval_required_tools=["payment-api"],
        )
    )
    await repository.upsert_tool_definition(
        ToolDefinitionRecord(
            tool_name="payment-api",
            description="Submits a payment",
            input_schema={"type": "object"},
            requires_approval=False,
        )
    )
    return app


async def _create_waiting_run(client: AsyncClient, app) -> tuple[str, str]:
    response = await client.post("/v1/runs", json={"tenant_id": "tenant-a", "objective": "submit payment"})
    assert response.status_code == 201
    run_id = response.json()["run_id"]
    await _wait_for_run_status(client, run_id, "waiting_for_approval")
    repository = app.state.run_service._repository
    agents = await repository.list_agents(run_id)
    latest_checkpoint = await repository.get_latest_checkpoint(run_id, agents[0].agent_id)
    assert latest_checkpoint is not None
    approval_id = latest_checkpoint.payload["approval_id"]
    return run_id, approval_id


async def _wait_for_run_status(client: AsyncClient, run_id: str, status: str) -> dict[str, object]:
    payload: dict[str, object] = {}
    for _ in range(40):
        response = await client.get(f"/v1/runs/{run_id}")
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {status}: {payload}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=BASELINE_PATH)
    parser.add_argument("--tmp-dir", type=Path, default=Path(".perf-tmp"))
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmup-iterations", type=int, default=DEFAULT_WARMUP_ITERATIONS)
    args = parser.parse_args()

    async def _write() -> None:
        args.tmp_dir.mkdir(parents=True, exist_ok=True)
        await write_core_api_baseline(
            output_path=args.output,
            tmp_path=args.tmp_dir,
            iterations=args.iterations,
            warmup_iterations=args.warmup_iterations,
        )

    asyncio.run(_write())


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the harness smoke test to verify it passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_benchmark.py -v`
Expected: PASS

- [ ] **Step 8: Checkpoint changes locally**

```bash
git add tests/perf/__init__.py tests/perf/benchmarks/__init__.py tests/perf/benchmarks/core_api.py tests/perf/test_core_api_benchmark.py
git commit -m "feat: add core api benchmark harness"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 2: Add The Repository Baseline Sample And Regression Guard

**Files:**
- Create: `tests/perf/baselines/core_api_baseline.json`
- Create: `tests/perf/test_core_api_regression.py`
- Modify: `tests/perf/benchmarks/core_api.py`

- [ ] **Step 1: Write the failing regression tests**

```python
# tests/perf/test_core_api_regression.py
import json

import pytest

from tests.perf.benchmarks.core_api import BASELINE_PATH, run_core_api_benchmarks


def test_core_api_baseline_file_exists() -> None:
    assert BASELINE_PATH.exists(), f"performance baseline missing: {BASELINE_PATH}"


@pytest.mark.asyncio
async def test_core_api_benchmark_stays_within_baseline_tolerance(tmp_path) -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    report = await run_core_api_benchmarks(
        tmp_path=tmp_path,
        iterations=1,
        warmup_iterations=0,
    )

    current_by_name = {item["scenario"]: item for item in report["scenarios"]}
    for baseline_item in baseline["scenarios"]:
        scenario = baseline_item["scenario"]
        current_item = current_by_name[scenario]
        tolerance = baseline_item["degradation_tolerance_ratio"]

        assert current_item["latency_ms_p95"] <= baseline_item["latency_ms_p95"] * (1 + tolerance)
        assert current_item["throughput_ops_per_sec"] >= baseline_item["throughput_ops_per_sec"] * (1 - tolerance)
```

- [ ] **Step 2: Run the regression tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_regression.py -v`
Expected: FAIL because `tests/perf/baselines/core_api_baseline.json` does not exist yet

- [ ] **Step 3: Improve comparison helpers and failure messages**

```python
# tests/perf/benchmarks/core_api.py
def compare_report_to_baseline(report: dict[str, object], baseline: dict[str, object]) -> list[str]:
    current_by_name = {item["scenario"]: item for item in report["scenarios"]}
    failures: list[str] = []
    for baseline_item in baseline["scenarios"]:
        scenario = baseline_item["scenario"]
        current_item = current_by_name[scenario]
        tolerance = baseline_item["degradation_tolerance_ratio"]

        latency_limit = baseline_item["latency_ms_p95"] * (1 + tolerance)
        if current_item["latency_ms_p95"] > latency_limit:
            failures.append(
                f"{scenario} p95 latency regressed: current={current_item['latency_ms_p95']:.3f}ms "
                f"baseline={baseline_item['latency_ms_p95']:.3f}ms tolerance={tolerance:.2f}"
            )

        throughput_floor = baseline_item["throughput_ops_per_sec"] * (1 - tolerance)
        if current_item["throughput_ops_per_sec"] < throughput_floor:
            failures.append(
                f"{scenario} throughput regressed: current={current_item['throughput_ops_per_sec']:.3f}ops/s "
                f"baseline={baseline_item['throughput_ops_per_sec']:.3f}ops/s tolerance={tolerance:.2f}"
            )
    return failures
```

```python
# tests/perf/test_core_api_regression.py
from tests.perf.benchmarks.core_api import BASELINE_PATH, compare_report_to_baseline, run_core_api_benchmarks


@pytest.mark.asyncio
async def test_core_api_benchmark_stays_within_baseline_tolerance(tmp_path) -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    report = await run_core_api_benchmarks(tmp_path=tmp_path, iterations=1, warmup_iterations=0)
    failures = compare_report_to_baseline(report, baseline)
    assert not failures, "\n".join(failures)
```

- [ ] **Step 4: Generate the first baseline JSON sample**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m tests.perf.benchmarks.core_api --output tests/perf/baselines/core_api_baseline.json --tmp-dir .perf-tmp --iterations 5 --warmup-iterations 1`
Expected: command completes successfully and writes `tests/perf/baselines/core_api_baseline.json`

- [ ] **Step 5: Keep the baseline file in the expected shape**

```json
{
  "baseline_name": "core_api",
  "generated_at": "2026-05-17T00:00:00+00:00",
  "python_version": "3.11.0",
  "scenario_count": 4,
  "scenarios": [
    {
      "scenario": "run_create_complete",
      "iterations": 5,
      "warmup_iterations": 1,
      "latency_ms_p50": 0.0,
      "latency_ms_p95": 0.0,
      "latency_ms_max": 0.0,
      "throughput_ops_per_sec": 0.0,
      "degradation_tolerance_ratio": 0.5
    }
  ]
}
```

- [ ] **Step 6: Run the regression tests to verify they pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_regression.py -v`
Expected: PASS

- [ ] **Step 7: Checkpoint changes locally**

```bash
git add tests/perf/benchmarks/core_api.py tests/perf/baselines/core_api_baseline.json tests/perf/test_core_api_regression.py
git commit -m "test: add performance baseline regression guard"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 3: Add Operator Documentation And Verify The Full Suite

**Files:**
- Create: `docs/performance-baseline.md`
- Modify: `docs/superpowers/specs/2026-05-17-agent-runtime-m4-performance-baseline-design.md`

- [ ] **Step 1: Write the performance baseline operating document**

```markdown
# Performance Baseline

## Scope

This repository stores a first-generation local performance baseline for the runtime core. The current scope covers:

- `run_create_complete`
- `run_create_wait_for_approval`
- `approval_approve_resume_complete`
- `metrics_scrape`

Deferred items:

- multi-agent benchmarks
- mixed regression gates with absolute limits
- real HTTP server benchmark mode

## Generate Or Refresh The Baseline

Run:

`C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m tests.perf.benchmarks.core_api --output tests/perf/baselines/core_api_baseline.json --tmp-dir .perf-tmp --iterations 5 --warmup-iterations 1`

This rewrites the repository baseline JSON using the current local environment.

## Run The Regression Check

Run:

`C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_benchmark.py tests/perf/test_core_api_regression.py -v`

## Interpret Failures

- A missing baseline file means the repository baseline has not been generated.
- A regression failure means current p95 latency or throughput exceeded the saved relative tolerance.
- These results are local comparison signals, not production SLO or capacity claims.
```

- [ ] **Step 2: Verify the approved spec still matches the planned implementation**

Run: `rg -n "poll|waiting_for_approval|50%|0.5" docs/superpowers/specs/2026-05-17-agent-runtime-m4-performance-baseline-design.md docs/superpowers/plans/2026-05-17-agent-runtime-m4-performance-baseline.md`
Expected: spec and plan both describe polling-based completion/waiting observation and `50%` relative degradation tolerance

- [ ] **Step 3: Run focused performance tests**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_benchmark.py tests/perf/test_core_api_regression.py -v`
Expected: PASS

- [ ] **Step 4: Run the full test suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS with the new performance baseline coverage included

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add docs/performance-baseline.md docs/superpowers/specs/2026-05-17-agent-runtime-m4-performance-baseline-design.md docs/superpowers/plans/2026-05-17-agent-runtime-m4-performance-baseline.md
git commit -m "docs: add runtime performance baseline guidance"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.
