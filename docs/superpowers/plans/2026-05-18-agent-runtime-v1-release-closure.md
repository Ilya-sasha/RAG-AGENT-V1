# Agent Runtime V1 Release Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current codebase into a first-release package that can be started locally, reproduced by another developer, run through a containerized path, and operated through documented day-1 guidance without adding new product features.

**Architecture:** This phase is a release-closure phase, not a feature-expansion phase. The work stays concentrated in entrypoint standardization, container assets, documentation, and acceptance verification. Existing runtime behavior remains the product baseline; this plan only fills gaps that block startup reproducibility, handoff, and operational clarity.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2 async, aiosqlite, Docker, Docker Compose, pytest

---

## File Structure

### Created Files

- `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
  Main project entrypoint covering quick-start, standard setup, local run, verification, and links to deeper docs.

- `C:\Users\Ilya\PycharmProjects\AGENT\Dockerfile`
  Application image definition for containerized startup.

- `C:\Users\Ilya\PycharmProjects\AGENT\docker-compose.yml`
  Standardized container run path for v1 local/container startup.

- `C:\Users\Ilya\PycharmProjects\AGENT\.env.example`
  Example configuration surface for runtime paths and host/port values.

- `C:\Users\Ilya\PycharmProjects\AGENT\scripts\start-local.ps1`
  Standardized PowerShell startup path for the local Windows environment.

- `C:\Users\Ilya\PycharmProjects\AGENT\scripts\start-local.sh`
  Standardized shell startup path for generic developer environments.

### Modified Files

- `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`
  Evolve the existing runbook into the v1 standard-operations guide and align it with the new startup/config/container story.

- `C:\Users\Ilya\PycharmProjects\AGENT\docs\deferred-roadmap.md`
  Update active next phase / deferred items so the v1 closure boundary is explicit and post-v1 work remains visible.

- `C:\Users\Ilya\PycharmProjects\AGENT\pyproject.toml`
  Only if needed to expose optional packaging metadata or scripts for the standardized startup story. Avoid unnecessary changes.

### Verification Commands

- Focused smoke and workflow regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_app_smoke.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`

- Full workflow-focused regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`

- Full regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`

- Container smoke:
  `docker compose up --build`

### Task 1: Add Red Acceptance Coverage For Standardized Local Startup Assets

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_release_assets.py`

- [ ] **Step 1: Write failing tests for required release assets and documentation entrypoints**

```python
from pathlib import Path


def test_release_assets_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "README.md").exists()
    assert (root / "Dockerfile").exists()
    assert (root / "docker-compose.yml").exists()
    assert (root / ".env.example").exists()
    assert (root / "scripts" / "start-local.ps1").exists()
    assert (root / "scripts" / "start-local.sh").exists()


def test_release_docs_reference_supported_runtime_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "agent_rag" in readme
    assert "fresh environment" in readme
    assert "docker compose" in readme.lower()
    assert "/health" in readme
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_release_assets.py -v`
Expected: FAIL because the release assets do not exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_release_assets.py
git commit -m "test: add v1 release asset coverage"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 2: Standardize Local Startup Paths And Project Entry Documentation

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\.env.example`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\scripts\start-local.ps1`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\scripts\start-local.sh`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_release_assets.py`

- [ ] **Step 1: Add a standardized Windows quick-start script for the current machine path**

```powershell
param(
    [string]$PythonExe = "C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe",
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000,
    [string]$DbUrl = "sqlite+aiosqlite:///./runtime.db",
    [string]$EmbeddingModelRoot = "C:\models\embedding_models"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repoRoot "src"
$env:AGENT_RUNTIME_DB_URL = $DbUrl
$env:AGENT_RUNTIME_EMBEDDING_MODEL_ROOT = $EmbeddingModelRoot

& $PythonExe -m uvicorn agent_runtime.main:app --host $Host --port $Port
```

- [ ] **Step 2: Add a generic shell startup script for fresh-environment users**

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PYTHONPATH="${ROOT_DIR}/src"
export AGENT_RUNTIME_DB_URL="${AGENT_RUNTIME_DB_URL:-sqlite+aiosqlite:///./runtime.db}"
export AGENT_RUNTIME_EMBEDDING_MODEL_ROOT="${AGENT_RUNTIME_EMBEDDING_MODEL_ROOT:-/models/embedding_models}"

python -m uvicorn agent_runtime.main:app --host "${AGENT_RUNTIME_HOST:-127.0.0.1}" --port "${AGENT_RUNTIME_PORT:-8000}"
```

- [ ] **Step 3: Add `.env.example` documenting runtime configuration knobs**

```dotenv
AGENT_RUNTIME_HOST=127.0.0.1
AGENT_RUNTIME_PORT=8000
AGENT_RUNTIME_DB_URL=sqlite+aiosqlite:///./runtime.db
AGENT_RUNTIME_EMBEDDING_MODEL_ROOT=/models/embedding_models
PYTHONPATH=src
```

- [ ] **Step 4: Add `README.md` as the v1 handoff entrypoint**

```md
# Agent Runtime

## V1 Quick Start

### Path A: Existing `agent_rag` Environment

Use `scripts/start-local.ps1` from the repository root.

### Path B: Fresh Environment

1. Create a Python 3.11 virtual environment
2. Install the project and dev dependencies
3. Export `PYTHONPATH=src`
4. Run `scripts/start-local.sh`

## Health Check

Call `GET /health` and expect `{"status":"ok"}`.

## Container Path

Use `docker compose up --build`.

## Documentation

- `docs/operations-runbook.md`
- `docs/deferred-roadmap.md`
```

- [ ] **Step 5: Run release-asset tests to verify the local entrypoint assets now pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_release_assets.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example scripts/start-local.ps1 scripts/start-local.sh tests/integration/test_release_assets.py
git commit -m "feat: add v1 local startup assets"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 3: Add Container Startup Assets And Production-Oriented Deployment Guidance

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\Dockerfile`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\docker-compose.yml`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_release_assets.py`

- [ ] **Step 1: Add a Dockerfile for application startup**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

ENV PYTHONPATH=/app/src
ENV AGENT_RUNTIME_HOST=0.0.0.0
ENV AGENT_RUNTIME_PORT=8000
ENV AGENT_RUNTIME_DB_URL=sqlite+aiosqlite:///./runtime.db
ENV AGENT_RUNTIME_EMBEDDING_MODEL_ROOT=/models/embedding_models

CMD ["python", "-m", "uvicorn", "agent_runtime.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Add a `docker-compose.yml` startup path**

```yaml
services:
  agent-runtime:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      PYTHONPATH: /app/src
      AGENT_RUNTIME_DB_URL: sqlite+aiosqlite:///./runtime.db
      AGENT_RUNTIME_EMBEDDING_MODEL_ROOT: /models/embedding_models
    volumes:
      - ./runtime.db:/app/runtime.db
      - /models/embedding_models:/models/embedding_models:ro
```

- [ ] **Step 3: Expand `README.md` with container run and production-oriented deployment guidance**

```md
## Container Startup

Run:

```bash
docker compose up --build
```

## Production-Oriented Deployment Guidance

- keep `runtime.db` on persistent storage
- mount the embedding-model directory read-only
- keep host/port and DB path explicit through environment variables
- front the app with a reverse proxy or platform ingress
- treat this as a single-service deployment topology for v1
```
```

- [ ] **Step 4: Extend release-asset tests to assert container docs are present**

```python
def test_release_docs_reference_container_deployment_guidance() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8").lower()
    assert "docker compose up --build" in readme
    assert "production-oriented deployment" in readme
    assert "runtime.db" in readme
```

- [ ] **Step 5: Run release-asset tests to verify the container assets and docs pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_release_assets.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml README.md tests/integration/test_release_assets.py
git commit -m "feat: add v1 container startup assets"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 4: Upgrade The Operations Runbook For V1 Handoff

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`

- [ ] **Step 1: Rewrite the runbook header and prerequisites around v1 handoff reality**

```md
## Purpose And Scope

This runbook covers the v1 release closure operating model for Agent Runtime. It is intended for developers and operators starting the single-service runtime through local or containerized paths.

## Supported Paths

- local quick-start using `agent_rag`
- standard fresh-environment setup
- container startup using `docker compose`
```

- [ ] **Step 2: Add standard operations sections for logs, health, configuration, data paths, upgrade, and rollback**

```md
## Standard Operations

### Logs
- local process stdout/stderr
- container logs through `docker compose logs`

### Health Check
- `GET /health`
- expected response: `{"status":"ok"}`

### Data And Model Paths
- runtime state path
- embedding model root path

### Upgrade And Rollback Cautions
- keep DB path stable
- back up `runtime.db` before upgrading
- avoid in-place directory drift during restart
```

- [ ] **Step 3: Add a known-limitations section that explicitly names deferred items**

```md
## Known Limitations

- SQLite-backed single-service topology
- deferred `aiosqlite` warning cleanup
- deferred tracing work
- deferred workflow browser/history/governance enhancements
```

- [ ] **Step 4: Run a focused smoke subset to confirm the documented operator surfaces still pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_app_smoke.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/operations-runbook.md README.md
git commit -m "docs: expand v1 operations runbook"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 5: Finalize Deferred Boundary And Release Acceptance Evidence

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\deferred-roadmap.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\README.md`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\operations-runbook.md`

- [ ] **Step 1: Update the deferred roadmap so v1 closure and post-v1 work are explicit**

```md
## Active Next Phase

| Item | Status | Target Phase | Notes |
| --- | --- | --- | --- |
| V1 release closure | selected for immediate implementation | current phase | close startup, documentation, containerization, and acceptance gaps without adding new product features |
```

- [ ] **Step 2: Add a v1 acceptance checklist to the README or runbook**

```md
## V1 Acceptance Checklist

- local quick path starts successfully
- fresh environment path is documented end-to-end
- `/health` returns `{"status":"ok"}`
- container startup path is documented
- workflow-focused regression evidence is recorded
- full regression evidence is recorded
```

- [ ] **Step 3: Run workflow-focused regression**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`
Expected: PASS

- [ ] **Step 4: Run full regression**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS, with any pre-existing deferred warnings documented rather than silently ignored.

- [ ] **Step 5: Commit**

```bash
git add docs/deferred-roadmap.md README.md docs/operations-runbook.md
git commit -m "docs: finalize v1 release closure boundary"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Self-Review

- Spec coverage:
  - quick path using `agent_rag`: Tasks 1 and 2
  - standard fresh-environment path: Tasks 2 and 4
  - containerized startup path: Task 3
  - production-oriented container deployment guidance: Task 3
  - standard operations documentation: Task 4
  - deferred-boundary clarity and release evidence: Task 5

- Placeholder scan:
  - all tasks include exact file paths, test commands, and concrete deliverables
  - commit steps are preserved for workflow parity and explicitly marked non-executable unless later requested

- Type consistency:
  - runtime configuration names consistently use `AGENT_RUNTIME_*`
  - the release-asset tests validate the same file names this plan creates
  - no task depends on an undeclared new product feature
