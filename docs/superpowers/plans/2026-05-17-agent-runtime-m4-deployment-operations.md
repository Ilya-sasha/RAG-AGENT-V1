# Agent Runtime M4 Deployment And Operations Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single operator-facing runbook for private single-service deployment of the runtime core, covering startup, configuration, health, approval operations, recovery, troubleshooting, and M4 closure notes.

**Architecture:** This phase is documentation-only. It adds `docs/operations-runbook.md`, keeps the approved spec aligned with the actual API and runtime behavior, and verifies correctness through route/state consistency checks plus the existing automated test suite.

**Tech Stack:** Markdown documentation, Python 3.11+, FastAPI route surface, pytest verification

---

## File Structure

### Create

- `docs/operations-runbook.md`
  Single-source runbook for deployment and operations in the current single-service runtime shape.

### Modify

- `docs/superpowers/specs/2026-05-17-agent-runtime-m4-deployment-operations-design.md`
  Keep the spec aligned with the finalized runbook wording if any drift is found during implementation.
- `docs/superpowers/plans/2026-05-17-agent-runtime-m4-deployment-operations.md`
  This plan file.

## Task 1: Draft The Operations Runbook

**Files:**
- Create: `docs/operations-runbook.md`

- [ ] **Step 1: Write the runbook skeleton with the approved section structure**

```markdown
# Operations Runbook

## Purpose And Scope

## Runtime Topology

## Prerequisites

## Start And Stop

## Configuration

## Health And Observability

## Operational Workflows

## Recovery And Failure Handling

## Troubleshooting

## Known Risks And M4 Closure Follow-Up
```

- [ ] **Step 2: Fill startup, topology, and configuration sections with current implementation and deployment recommendation boundaries**

```markdown
## Runtime Topology

The current runtime is a single FastAPI service process with:

- HTTP API routes for runs, approvals, tools, tenants, health, and metrics
- a SQLite-backed runtime state store
- in-process structured logging and Prometheus text metrics
- startup-time resumption of active runs through the application lifespan

## Prerequisites

- Python `3.11+`
- installed repository dependencies
- `agent_rag` virtual environment or an equivalent Python environment
- repository root at `C:\Users\Ilya\PycharmProjects\AGENT`
- `PYTHONPATH=src`

## Start And Stop

Recommended start command in PowerShell:

`$env:PYTHONPATH='C:\Users\Ilya\PycharmProjects\AGENT\src'; C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m uvicorn agent_runtime.main:app --host 0.0.0.0 --port 8000`

Expected behavior:

- service exposes `GET /health`
- service exposes `GET /metrics`
- application startup initializes the database and resumes active runs

Graceful stop:

- stop the `uvicorn` process normally
- the runtime shutdown path cancels in-flight tasks before exit

## Configuration

### Current Implementation

- `create_app()` defaults `db_url` to `sqlite+aiosqlite:///./runtime.db`
- database location is relative to the current working directory unless overridden
- tool registry and model client wiring are in-process application configuration concerns

### Deployment Recommendation

- place the SQLite database on a stable persistent path
- keep the working directory stable across restarts
- inject model credentials through the deployment environment or wrapper process
- forward process logs to the operator's chosen log sink
```

- [ ] **Step 3: Fill health, workflow, recovery, troubleshooting, and known-risk sections with the current API surface**

```markdown
## Health And Observability

- `GET /health` returns `{"status": "ok"}`
- `GET /metrics` returns Prometheus text exposition
- runtime logs are structured and include request/run/agent context
- performance regression guidance lives in `docs/performance-baseline.md`

## Operational Workflows

### Register A Tool

Endpoint: `POST /v1/tools`

Example payload:

```json
{
  "tool_name": "payment-api",
  "description": "Submits a payment",
  "input_schema": {
    "type": "object",
    "properties": {
      "amount": { "type": "number" }
    }
  },
  "requires_approval": false
}
```

### Configure A Tenant Policy

Endpoint: `PUT /v1/tenants/{tenant_id}/policies`

Example payload:

```json
{
  "allowed_tools": ["payment-api"],
  "approval_required_tools": ["payment-api"]
}
```

### Create And Inspect A Run

- create: `POST /v1/runs`
- inspect: `GET /v1/runs/{run_id}`
- replay events: `GET /v1/runs/{run_id}/events/replay`
- manual resume: `POST /v1/runs/{run_id}/resume`

## Recovery And Failure Handling

- active runs are resumed on application startup
- approval waits remain operator-driven through the approval APIs
- event replay is the primary operator-facing execution history path
- terminal runs should not be expected to resume

## Troubleshooting

- `/health` failure: verify the process started and the configured bind/port is correct
- `/metrics` failure: verify the application is running and the metrics route is included
- `waiting_for_approval`: inspect approval state and resolve through the approval API
- `404` on tool or tenant lookup: verify the entity was registered in the current database
- resume not progressing: inspect replayed events and the latest visible run state

## Known Risks And M4 Closure Follow-Up

- current deployment model is single service plus SQLite
- no HA or multi-instance coordination guarantees exist in this phase
- startup-instruction enhancement is deferred until the wider project is complete
- multi-agent performance baseline remains deferred
- the `PytestUnhandledThreadExceptionWarning` from the `aiosqlite` worker thread remains a known issue and is explicitly part of the M4 closure cleanup plan
```

- [ ] **Step 4: Save the completed runbook**

```markdown
# Operations Runbook

## Purpose And Scope

This runbook is for operators deploying and running the current Agent Runtime implementation as a single service in a private environment or VPC. It describes the current runtime behavior and practical operating guidance for the existing codebase.

This document does not promise HA, autoscaling, or production capacity guarantees.
```

- [ ] **Step 5: Checkpoint changes locally**

```bash
git add docs/operations-runbook.md
git commit -m "docs: add operations runbook"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 2: Verify Runbook References Against The Current Codebase

**Files:**
- Modify: `docs/operations-runbook.md`
- Modify: `docs/superpowers/specs/2026-05-17-agent-runtime-m4-deployment-operations-design.md`

- [ ] **Step 1: Verify the runbook uses the correct route paths and state names**

Run: `rg -n "/health|/metrics|/v1/runs|/v1/approvals|/v1/tools|/v1/tenants|waiting_for_approval|runtime.db" docs/operations-runbook.md src/agent_runtime/api src/agent_runtime/runtime src/agent_runtime/domain`
Expected: matches the documented paths and the current state name `waiting_for_approval`

- [ ] **Step 2: Verify the runbook startup command matches the current entrypoint**

Run: `rg -n "agent_runtime.main:app|create_app|sqlite\\+aiosqlite:///\\./runtime.db" docs/operations-runbook.md src/agent_runtime/main.py src/agent_runtime/api/app.py`
Expected: runbook references the current `agent_runtime.main:app` entrypoint and default SQLite URL behavior

- [ ] **Step 3: If wording drift is found, update the runbook and spec inline**

```markdown
Update the affected section so the runbook describes only the current verified behavior and keeps deployment recommendations clearly labeled.
```

- [ ] **Step 4: Checkpoint changes locally**

```bash
git add docs/operations-runbook.md docs/superpowers/specs/2026-05-17-agent-runtime-m4-deployment-operations-design.md
git commit -m "docs: align deployment runbook with runtime behavior"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Task 3: Final Verification And M4 Documentation Closure

**Files:**
- Modify: `docs/operations-runbook.md`
- Modify: `docs/superpowers/plans/2026-05-17-agent-runtime-m4-deployment-operations.md`

- [ ] **Step 1: Run focused documentation consistency checks**

Run: `rg -n "Current Implementation|Deployment Recommendation|M4 closure cleanup plan|PytestUnhandledThreadExceptionWarning|performance-baseline" docs/operations-runbook.md docs/superpowers/specs/2026-05-17-agent-runtime-m4-deployment-operations-design.md`
Expected: the runbook distinguishes implementation vs recommendation, references the performance baseline doc, and lists the `aiosqlite` warning as an M4 closure cleanup item

- [ ] **Step 2: Run the full test suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS, with no regression introduced by the documentation changes

- [ ] **Step 3: Record completion status in the final response**

```markdown
Summarize:

- runbook path
- spec path
- verification result
- remaining M4 closure note for the `aiosqlite` thread warning
```

- [ ] **Step 4: Checkpoint changes locally**

```bash
git add docs/operations-runbook.md docs/superpowers/plans/2026-05-17-agent-runtime-m4-deployment-operations.md
git commit -m "docs: finalize m4 deployment and operations guidance"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.
