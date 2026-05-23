from __future__ import annotations

from typing import Protocol

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


class MetricsSink(Protocol):
    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None: ...

    def record_run_created(self) -> None: ...

    def record_run_completed(self) -> None: ...

    def record_run_failed(self) -> None: ...

    def record_approval_resolution(self, *, status: str) -> None: ...

    def record_agent_decision(self, *, kind: str) -> None: ...

    def record_tool_call(
        self,
        *,
        tool_name: str,
        status: str,
        duration_seconds: float,
    ) -> None: ...

    def record_knowledge_ingest(self, *, status: str) -> None: ...

    def record_retrieval_query(
        self,
        *,
        status: str,
        duration_seconds: float,
    ) -> None: ...

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
            "HTTP request duration in seconds",
            ["method", "route", "status_code"],
            registry=self._registry,
        )
        self._runs_created = Counter(
            "runtime_runs_created_total",
            "Runtime runs created",
            registry=self._registry,
        )
        self._runs_completed = Counter(
            "runtime_runs_completed_total",
            "Runtime runs completed",
            registry=self._registry,
        )
        self._runs_failed = Counter(
            "runtime_runs_failed_total",
            "Runtime runs failed",
            registry=self._registry,
        )
        self._approval_resolutions = Counter(
            "runtime_approval_resolutions_total",
            "Runtime approval resolutions",
            ["status"],
            registry=self._registry,
        )
        self._agent_decisions = Counter(
            "runtime_agent_decisions_total",
            "Runtime agent decisions",
            ["kind"],
            registry=self._registry,
        )
        self._tool_calls = Counter(
            "runtime_tool_calls_total",
            "Runtime tool calls",
            ["tool_name", "status"],
            registry=self._registry,
        )
        self._tool_call_duration = Histogram(
            "runtime_tool_call_duration_seconds",
            "Runtime tool call duration in seconds",
            ["tool_name", "status"],
            registry=self._registry,
        )
        self._knowledge_ingest_requests = Counter(
            "knowledge_ingest_requests_total",
            "Knowledge ingest requests",
            ["status"],
            registry=self._registry,
        )
        self._knowledge_retrieval_queries = Counter(
            "knowledge_retrieval_queries_total",
            "Knowledge retrieval queries",
            ["status"],
            registry=self._registry,
        )
        self._knowledge_retrieval_query_duration = Histogram(
            "knowledge_retrieval_query_duration_seconds",
            "Knowledge retrieval query duration in seconds",
            ["status"],
            registry=self._registry,
        )

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        labels = {
            "method": method,
            "route": route,
            "status_code": str(status_code),
        }
        self._http_requests.labels(**labels).inc()
        self._http_request_duration.labels(**labels).observe(duration_seconds)

    def record_run_created(self) -> None:
        self._runs_created.inc()

    def record_run_completed(self) -> None:
        self._runs_completed.inc()

    def record_run_failed(self) -> None:
        self._runs_failed.inc()

    def record_approval_resolution(self, *, status: str) -> None:
        self._approval_resolutions.labels(status=status).inc()

    def record_agent_decision(self, *, kind: str) -> None:
        self._agent_decisions.labels(kind=kind).inc()

    def record_tool_call(
        self,
        *,
        tool_name: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        labels = {"tool_name": tool_name, "status": status}
        self._tool_calls.labels(**labels).inc()
        self._tool_call_duration.labels(**labels).observe(duration_seconds)

    def record_knowledge_ingest(self, *, status: str) -> None:
        self._knowledge_ingest_requests.labels(status=status).inc()

    def record_retrieval_query(
        self,
        *,
        status: str,
        duration_seconds: float,
    ) -> None:
        self._knowledge_retrieval_queries.labels(status=status).inc()
        self._knowledge_retrieval_query_duration.labels(status=status).observe(duration_seconds)

    def render_prometheus_text(self) -> str:
        return generate_latest(self._registry).decode("utf-8")
