#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PYTHONPATH="${ROOT_DIR}/src"
export AGENT_RUNTIME_DB_URL="${AGENT_RUNTIME_DB_URL:-sqlite+aiosqlite:///./runtime.db}"
export AGENT_RUNTIME_EMBEDDING_MODEL_ROOT="${AGENT_RUNTIME_EMBEDDING_MODEL_ROOT:-C:\models\embedding_models\iic\nlp_gte_sentence-embedding_chinese-base}"
export AGENT_RUNTIME_MODEL_BASE_URL="${AGENT_RUNTIME_MODEL_BASE_URL:-https://api.deepseek.com}"
export AGENT_RUNTIME_MODEL_NAME="${AGENT_RUNTIME_MODEL_NAME:-deepseek-v4-flash}"
export AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS="${AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS:-60}"

if [[ -n "${AGENT_RUNTIME_MODEL_API_KEY:-}" ]]; then
  export AGENT_RUNTIME_MODEL_API_KEY
fi

cd "${ROOT_DIR}"

python -m uvicorn agent_runtime.main:app --host "${AGENT_RUNTIME_HOST:-127.0.0.1}" --port "${AGENT_RUNTIME_PORT:-8000}"
