import json
import subprocess

import pytest

from agent_runtime.knowledge.embedding import SubprocessEmbeddingProvider


def test_subprocess_embedding_provider_returns_worker_vectors(monkeypatch) -> None:
    recorded_command: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        recorded_command["args"] = args
        recorded_command["kwargs"] = kwargs
        payload = {"vectors": [[0.6, 0.8], [0.0, 1.0]]}
        return subprocess.CompletedProcess(
            args=kwargs["args"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr("agent_runtime.knowledge.embedding.subprocess.run", fake_run)

    provider = SubprocessEmbeddingProvider(
        "models/test",
        python_executable="python-test",
        worker_timeout_seconds=12,
    )

    result = provider.embed_documents(["doc 1", "doc 2"])

    assert result == [[0.6, 0.8], [0.0, 1.0]]
    assert provider.embed_query("query") == [0.6, 0.8]
    assert recorded_command["kwargs"]["timeout"] == 12
    assert recorded_command["kwargs"]["text"] is True
    assert recorded_command["kwargs"]["encoding"] == "utf-8"


def test_subprocess_embedding_provider_raises_runtime_error_when_worker_exits_non_zero(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=kwargs["args"],
            returncode=3221225477,
            stdout="",
            stderr="access violation",
        )

    monkeypatch.setattr("agent_runtime.knowledge.embedding.subprocess.run", fake_run)

    provider = SubprocessEmbeddingProvider("models/test", python_executable="python-test")

    with pytest.raises(RuntimeError, match="access violation"):
        provider.embed_query("query")
