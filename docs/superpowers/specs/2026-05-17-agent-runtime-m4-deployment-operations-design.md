# Agent Runtime M4 Deployment And Operations Documentation Design

**Date:** 2026-05-17

**Status:** Draft for review

## 1. Goal

Add a production-hardening runbook for the current runtime core so an operator can deploy and operate the system as a single service inside a private environment or VPC with clear guidance for startup, health checks, approval handling, recovery, and troubleshooting.

This phase is documentation-first. It does not add deployment automation, orchestration assets, or new runtime features.

## 2. Scope

### In Scope

- one operator-facing runbook document for private-environment single-service deployment
- startup and shutdown guidance for the current FastAPI runtime service
- configuration guidance covering both current implementation and recommended deployment conventions
- runbook workflows for run inspection, approval handling, event replay, and manual resume
- health, metrics, logging, and recovery guidance based on the current implementation
- known-risk and M4-closure follow-up notes

### Out of Scope

- Docker, Kubernetes, or other container deployment assets
- Windows service, `systemd`, or process-manager setup files
- environment-file templates or secrets-manager integrations
- code changes for deployment convenience
- cleanup of the existing `aiosqlite` thread warning during this documentation phase

## 3. Design Principles

- the runbook must describe the current system truth, not an aspirational future platform
- current implementation details and deployment recommendations must be labeled separately
- operator workflows must be written around existing API endpoints and verified runtime behaviors
- the first deployment guide must stay scoped to the current single-service runtime shape
- known operational gaps must be documented explicitly instead of being hidden behind vague language

## 4. Deployment Assumption

The first-generation runbook assumes:

- one FastAPI runtime service process
- one local or attached filesystem path for the SQLite runtime database
- one private network or VPC-style environment
- direct operator access to process logs and HTTP endpoints

This phase does not describe a high-availability topology or multi-instance coordination model.

## 5. Deliverable

Create one document:

- `docs/operations-runbook.md`

This file is the single source for deployment and operations guidance in the current phase.

## 6. Runbook Structure

The runbook should use the following sections.

### 6.1 Purpose And Scope

Explain:

- what the runtime is
- who the runbook is for
- that this is a first-generation single-service operating guide
- that the document does not claim HA, autoscaling, or production capacity guarantees

### 6.2 Runtime Topology

Describe the current service shape:

- FastAPI application process
- SQLite state database
- in-process metrics endpoint
- API-driven approval and recovery operations

### 6.3 Prerequisites

Document the runtime prerequisites that are true in the current repository:

- Python `3.11+`
- installed project dependencies
- working environment such as the existing `agent_rag` virtual environment
- repository path and `PYTHONPATH=src`

### 6.4 Start And Stop

Document:

- recommended process start command for the current codebase
- expected bind behavior and app entrypoint
- graceful stop expectations
- restart expectations

This section should stay within current capabilities and must not introduce a future process manager story as if it already exists.

### 6.5 Configuration

Split this section into two explicit categories:

1. `Current Implementation`
   Document values and behaviors that exist today, including:
   - `create_app(db_url=...)`
   - default SQLite URL shape
   - default runtime database filename behavior

2. `Deployment Recommendation`
   Document recommended conventions that do not require code changes, including:
   - placing the database on a persistent filesystem path
   - keeping runtime working directories stable across restarts
   - injecting model credentials through the deployment environment or wrapper process
   - forwarding logs to the operator's chosen log sink

### 6.6 Health And Observability

Document the current observability surfaces:

- `GET /health`
- `GET /metrics`
- structured runtime logs
- reference to the existing performance baseline document

This section must not describe tracing or dashboards as current capabilities.

### 6.7 Operational Workflows

Document concrete workflows around current endpoints:

- register a tool
- configure tenant tool policy
- create a run
- inspect a run
- replay run events
- inspect an approval request
- approve or reject an approval request
- manually resume a run

Each workflow should include:

- the operator intent
- the endpoint to call
- the expected success shape or state transition

### 6.8 Recovery And Failure Handling

Document the current verified recovery model:

- active run recovery on service startup
- approval-wait recovery behavior
- replay and checkpoint-oriented inspection
- terminal-state boundaries

This section should be explicit that recovery semantics are validated for the current single-service model only.

### 6.9 Troubleshooting

Document focused failure scenarios such as:

- service starts but `/health` fails
- `/metrics` is unavailable
- a run remains in `waiting_for_approval`
- a tool or tenant policy lookup returns `404`
- a resumed run does not move forward

Each item should describe:

- likely cause
- what to inspect first
- the current recovery or mitigation path

### 6.10 Known Risks And M4 Closure Follow-Up

Document the known operational limitations and deferred cleanup items, including:

- current runtime shape is single service plus SQLite
- no HA or multi-instance coordination guarantees
- startup-instruction enhancement is deferred until the wider project is complete
- multi-agent performance baseline is deferred to a later phase
- the `PytestUnhandledThreadExceptionWarning` emitted from the `aiosqlite` worker thread during cancellation tests is a known issue and is explicitly part of the M4 closure cleanup plan

## 7. Content Boundaries

The runbook should not:

- promise production SLOs
- document container deployment artifacts that do not exist
- imply tracing, dashboards, or secrets-management integrations already exist
- convert deployment recommendations into statements of implemented runtime behavior

It should:

- help an operator run the current system on a private single-service deployment
- make existing inspection and recovery paths discoverable
- document current limitations without ambiguity

## 8. Verification Strategy

This phase should verify:

- runbook references match current route paths and state names
- runbook recovery guidance matches tested runtime behavior
- no code paths are changed while adding the documentation

The implementation phase does not need a special document-testing framework. Existing automated tests remain the regression gate.

## 9. Acceptance Criteria

This phase is complete when:

- `docs/operations-runbook.md` exists
- the document covers startup, configuration, health, metrics, approval handling, recovery, troubleshooting, and known risks
- the document clearly distinguishes current implementation from deployment recommendation
- the `aiosqlite` thread warning is listed as an M4 closure cleanup item rather than being silently ignored
