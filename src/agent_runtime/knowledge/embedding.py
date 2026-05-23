from __future__ import annotations

import json
import os
import subprocess
import sys
from math import sqrt
from pathlib import Path
from typing import Any


def _normalize_vector(values: Any) -> list[float]:
    vector = [float(value) for value in values]
    magnitude = sqrt(sum(value * value for value in vector))
    if magnitude == 0.0:
        return vector
    return [value / magnitude for value in vector]


class LocalEmbeddingProvider:
    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._model = None

    def provider_id(self) -> str:
        return "local-default"

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer(self._model_path)
            except Exception as exc:
                raise RuntimeError(
                    "failed to load embedding model from "
                    f"{self._model_path!r}; set AGENT_RUNTIME_EMBEDDING_MODEL_ROOT to a concrete "
                    "sentence-transformers model directory"
                ) from exc
        return self._model

    def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        encoded = self._get_model().encode(chunks, normalize_embeddings=False)
        return [_normalize_vector(vector) for vector in encoded]

    def embed_query(self, query: str) -> list[float]:
        encoded = self._get_model().encode(query, normalize_embeddings=False)
        return _normalize_vector(encoded)


class SubprocessEmbeddingProvider:
    def __init__(
        self,
        model_path: str,
        *,
        python_executable: str | None = None,
        worker_timeout_seconds: float = 60,
    ) -> None:
        self._model_path = model_path
        self._python_executable = python_executable or sys.executable
        self._worker_timeout_seconds = worker_timeout_seconds

    def provider_id(self) -> str:
        return "local-default"

    def embed_documents(self, chunks: list[str]) -> list[list[float]]:
        return self._run_worker("documents", chunks)

    def embed_query(self, query: str) -> list[float]:
        return self._run_worker("query", [query])[0]

    def _run_worker(self, mode: str, inputs: list[str]) -> list[list[float]]:
        env = dict(os.environ)
        src_root = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = src_root if not existing_pythonpath else os.pathsep.join([src_root, existing_pythonpath])
        payload = json.dumps(
            {
                "model_path": self._model_path,
                "mode": mode,
                "inputs": inputs,
            }
        )
        completed = subprocess.run(
            args=[self._python_executable, "-m", "agent_runtime.knowledge.embedding_worker"],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self._worker_timeout_seconds,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or f"exit code {completed.returncode}").strip()
            raise RuntimeError(f"embedding worker failed for {self._model_path!r}: {detail}")
        try:
            worker_payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("embedding worker returned invalid JSON output") from exc

        vectors = worker_payload.get("vectors")
        if not isinstance(vectors, list) or not vectors:
            raise RuntimeError("embedding worker returned no vectors")
        return [[float(value) for value in vector] for vector in vectors]
