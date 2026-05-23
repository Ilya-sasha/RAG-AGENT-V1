import json

import pytest

from tests.perf.benchmarks.core_api import (
    BASELINE_PATH,
    compare_report_to_baseline,
    DEFAULT_ITERATIONS,
    DEFAULT_WARMUP_ITERATIONS,
    run_core_api_benchmarks,
)


def test_core_api_baseline_file_exists() -> None:
    assert BASELINE_PATH.exists(), f"performance baseline missing: {BASELINE_PATH}"


def _baseline_run_settings(baseline: dict[str, object]) -> tuple[int, int]:
    scenarios = baseline.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return DEFAULT_ITERATIONS, DEFAULT_WARMUP_ITERATIONS

    first = scenarios[0]
    if not isinstance(first, dict):
        return DEFAULT_ITERATIONS, DEFAULT_WARMUP_ITERATIONS

    iterations = first.get("iterations")
    warmup_iterations = first.get("warmup_iterations")
    return (
        int(iterations) if isinstance(iterations, int) and iterations > 0 else DEFAULT_ITERATIONS,
        int(warmup_iterations)
        if isinstance(warmup_iterations, int) and warmup_iterations >= 0
        else DEFAULT_WARMUP_ITERATIONS,
    )


@pytest.mark.asyncio
async def test_core_api_benchmark_stays_within_baseline_tolerance(tmp_path) -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    iterations, warmup_iterations = _baseline_run_settings(baseline)
    failure_reports: list[str] = []
    for attempt in range(2):
        report = await run_core_api_benchmarks(
            tmp_path=tmp_path / f"attempt-{attempt}",
            iterations=iterations,
            warmup_iterations=warmup_iterations,
        )
        failures = compare_report_to_baseline(report, baseline)
        if not failures:
            return
        failure_reports.append(f"attempt {attempt + 1}: " + "; ".join(failures))

    raise AssertionError("\n".join(failure_reports))
