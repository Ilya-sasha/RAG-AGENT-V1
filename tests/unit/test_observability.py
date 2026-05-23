import logging

from agent_runtime.observability.logging import build_log_payload, emit_structured_log
from agent_runtime.observability.metrics import PrometheusMetricsSink


def test_prometheus_metrics_sink_exports_expected_counters() -> None:
    sink = PrometheusMetricsSink()

    sink.record_run_created()
    sink.record_http_request(
        method="GET",
        route="/health",
        status_code=200,
        duration_seconds=0.01,
    )
    sink.record_knowledge_ingest(status="success")
    sink.record_retrieval_query(status="success", duration_seconds=0.02)

    payload = sink.render_prometheus_text()

    assert "runtime_runs_created_total" in payload
    assert 'http_requests_total{method="GET",route="/health",status_code="200"} 1.0' in payload
    assert 'knowledge_ingest_requests_total{status="success"} 1.0' in payload
    assert 'knowledge_retrieval_queries_total{status="success"} 1.0' in payload
    assert 'knowledge_retrieval_query_duration_seconds_count{status="success"} 1.0' in payload


def test_build_log_payload_merges_context_and_fields() -> None:
    payload = build_log_payload(
        "run created",
        component="run_service",
        context={"request_id": "req-1", "run_id": "run-1"},
        fields={"status": "created"},
    )

    assert payload["message"] == "run created"
    assert payload["component"] == "run_service"
    assert payload["request_id"] == "req-1"
    assert payload["run_id"] == "run-1"
    assert payload["status"] == "created"


def test_emit_structured_log_does_not_raise_when_handler_fails() -> None:
    class FailingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("boom")

    logger = logging.getLogger("test.observability")
    logger.handlers = [FailingHandler()]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    emit_structured_log(logger, "safe", component="test", context={}, fields={})
