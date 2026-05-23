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

`C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m tests.perf.benchmarks.core_api --output tests/perf/baselines/core_api_baseline.json --tmp-dir .perf-tmp --iterations 10 --warmup-iterations 2`

This rewrites the repository baseline JSON using the current local environment.

## Run The Regression Check

Run:

`C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/perf/test_core_api_benchmark.py tests/perf/test_core_api_regression.py -v`

## Interpret Failures

- A missing baseline file means the repository baseline has not been generated.
- A regression failure means current p95 latency or throughput exceeded the saved relative tolerance.
- These results are local comparison signals, not production SLO or capacity claims.
