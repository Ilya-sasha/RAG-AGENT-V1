FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    AGENT_RUNTIME_HOST=0.0.0.0 \
    AGENT_RUNTIME_PORT=8000 \
    AGENT_RUNTIME_DB_URL=sqlite+aiosqlite:////data/runtime.db \
    AGENT_RUNTIME_EMBEDDING_MODEL_ROOT=/models/embedding_models

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir --no-build-isolation .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn agent_runtime.main:app --host ${AGENT_RUNTIME_HOST} --port ${AGENT_RUNTIME_PORT}"]
