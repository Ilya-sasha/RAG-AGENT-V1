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
