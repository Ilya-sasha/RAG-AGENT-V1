from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles
from typing import Any

from httpx import ASGITransport, AsyncClient

SRC_PATH = Path(__file__).resolve().parents[3] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.domain.models import TenantPolicyRecord, ToolDefinitionRecord
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.tools.base import ToolExecutionRequest, ToolExecutionResult, ToolExecutor
from agent_runtime.tools.registry import ToolRegistry

BASELINE_PATH = Path(__file__).resolve().parents[1] / "baselines" / "core_api_baseline.json"
DEFAULT_ITERATIONS = 10
DEFAULT_WARMUP_ITERATIONS = 2
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
    scenarios: list[tuple[str, Callable[[Path], Awaitable[float]]]] = [
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
    degradation_tolerance_ratio: float = DEFAULT_DEGRADATION_TOLERANCE_RATIO,
) -> dict[str, object]:
    report = await run_core_api_benchmarks(
        tmp_path=tmp_path,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        degradation_tolerance_ratio=degradation_tolerance_ratio,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def compare_report_to_baseline(report: dict[str, object], baseline: dict[str, object]) -> list[str]:
    failures: list[str] = []
    current_items = report.get("scenarios")
    baseline_items = baseline.get("scenarios")
    if not isinstance(current_items, list) or not isinstance(baseline_items, list):
        return ["benchmark report or baseline is missing the 'scenarios' list"]

    current_by_name = {
        item["scenario"]: item for item in current_items if isinstance(item, dict) and "scenario" in item
    }
    for baseline_item in baseline_items:
        if not isinstance(baseline_item, dict):
            failures.append("baseline contains a non-object scenario entry")
            continue

        scenario = baseline_item["scenario"]
        current_item = current_by_name.get(scenario)
        if current_item is None:
            failures.append(f"current report missing scenario: {scenario}")
            continue

        tolerance = float(baseline_item["degradation_tolerance_ratio"])

        latency_limit = float(baseline_item["latency_ms_p95"]) * (1 + tolerance)
        current_latency = float(current_item["latency_ms_p95"])
        if current_latency > latency_limit:
            failures.append(
                f"{scenario} p95 latency regressed: current={current_latency:.3f}ms "
                f"baseline={float(baseline_item['latency_ms_p95']):.3f}ms tolerance={tolerance:.2f}"
            )

        throughput_floor = float(baseline_item["throughput_ops_per_sec"]) * (1 - tolerance)
        current_throughput = float(current_item["throughput_ops_per_sec"])
        if current_throughput < throughput_floor:
            failures.append(
                f"{scenario} throughput regressed: current={current_throughput:.3f}ops/s "
                f"baseline={float(baseline_item['throughput_ops_per_sec']):.3f}ops/s tolerance={tolerance:.2f}"
            )

    return failures


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
        warmup_dir = scenario_tmp / f"warmup-{index}"
        warmup_dir.mkdir(parents=True, exist_ok=True)
        await runner(warmup_dir)

    latencies: list[float] = []
    started = time.perf_counter()
    for index in range(iterations):
        iteration_dir = scenario_tmp / f"iteration-{index}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        latency_ms = await runner(iteration_dir)
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
    buckets = quantiles(values, n=100, method="inclusive")
    return buckets[percentile - 1]


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
    async with _app_client_context(app) as client:
        latency_ms, approval_id = await _measure_create_to_waiting(client, app)
        response = await client.post(
            f"/v1/approvals/{approval_id}/reject",
            json={"resolution_note": "benchmark cleanup"},
        )
        assert response.status_code == 200
        return latency_ms


async def _measure_approval_approve_resume_complete(workdir: Path) -> float:
    app = await _build_approval_app(workdir, finish_after_tool=True)
    async with _app_client_context(app) as client:
        run_id, approval_id = await _create_waiting_run(client, app)
        started = time.perf_counter()
        response = await client.post(
            f"/v1/approvals/{approval_id}/approve",
            json={"resolution_note": "benchmark approval"},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 200
        final_payload = await _wait_for_run_status(client, run_id, "completed")
        assert final_payload["result"] == "payment submitted"
        return elapsed_ms


async def _measure_metrics_scrape(workdir: Path) -> float:
    app = create_app(db_url=f"sqlite+aiosqlite:///{workdir / 'runtime.db'}")
    async with _app_client_context(app) as client:
        started = time.perf_counter()
        response = await client.get("/metrics")
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.status_code == 200
        return elapsed_ms


async def _measure_create_to_status(app: Any, *, target_status: str) -> float:
    async with _app_client_context(app) as client:
        started = time.perf_counter()
        response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "benchmark"},
        )
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        await _wait_for_run_status(client, run_id, target_status)
        return (time.perf_counter() - started) * 1000


async def _measure_create_to_waiting(client: AsyncClient, app: Any) -> tuple[float, str]:
    started = time.perf_counter()
    _, approval_id = await _create_waiting_run(client, app)
    return (time.perf_counter() - started) * 1000, approval_id


@asynccontextmanager
async def _app_client_context(app: Any):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            yield client


async def _build_approval_app(workdir: Path, *, finish_after_tool: bool) -> Any:
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


async def _create_waiting_run(client: AsyncClient, app: Any) -> tuple[str, str]:
    response = await client.post(
        "/v1/runs",
        json={"tenant_id": "tenant-a", "objective": "submit payment"},
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]
    await _wait_for_run_status(client, run_id, "waiting_for_approval")
    approval_id = await _wait_for_approval_id(client, run_id)
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


async def _wait_for_approval_id(client: AsyncClient, run_id: str) -> str:
    for _ in range(40):
        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        assert replay_response.status_code == 200
        for event in reversed(replay_response.json()["events"]):
            if event["event_type"] == "approval.requested":
                approval_id = event["payload"].get("approval_id")
                if isinstance(approval_id, str):
                    return approval_id
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not expose approval.requested in replay events")


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
