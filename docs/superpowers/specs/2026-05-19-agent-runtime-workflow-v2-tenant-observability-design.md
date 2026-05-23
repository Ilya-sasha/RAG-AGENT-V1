# Agent Runtime Workflow V2 Tenant Observability Design

## Summary

This design defines the first post-v1 workflow platform expansion slice: a tenant-scoped workflow observability API for platform and operations users. The delivery remains API-first and focuses on workflow-started runs only. It builds on the shipped `/v1/workflows` and runtime event/checkpoint surfaces without changing the existing workflow launch or run execution write paths.

## Problem

The current v1 runtime can launch and execute workflows, replay run events, persist checkpoints, and track approvals, but its read surface is still run-centric instead of observability-centric:

- operators can fetch a single run when they already know `run_id`
- operators can replay events, but only after they already know which run to inspect
- operators cannot list workflow runs for a tenant with workflow-aware filters
- operators cannot quickly identify why a workflow run is blocked or failed without manually correlating multiple low-level records

For the next phase, the highest-value gap is a tenant-level workflow run observation surface that lets platform and operations users query workflow runs, filter them, and understand blocking or failure states quickly.

## Users

Primary user:

- platform or operations users responsible for monitoring tenant workflow activity and triaging failures

Secondary user:

- workflow developers who need a more structured run observation view during debugging

## Goals

- Provide a tenant-scoped list API for workflow-started runs.
- Support filterable workflow run queries by workflow, version, status, and time range.
- Provide a workflow run detail API that summarizes the current observation state for a single run.
- Translate low-level runtime records into operator-readable blocking and failure summaries.
- Reuse the existing runtime persistence model and event replay surface.
- Keep the implementation API-first so a lightweight UI can be added later on stable contracts.

## Non-Goals

- No visual control panel or workflow observability UI in this phase.
- No cross-tenant or global platform observability surface.
- No inclusion of non-workflow runs in this observability layer.
- No tracing rollout or distributed span model.
- No redesign of runtime execution, workflow launch, or event emission.
- No governance, release approval, or workflow management expansion beyond observation APIs.
- No new write path for workflow telemetry beyond the currently persisted runtime and workflow link data.

## Scope Boundary

This phase covers tenant-scoped observability for workflow-started runs only.

Included:

- workflow run list query surface
- workflow run detail query surface
- filter semantics
- pagination semantics
- observation status derivation
- blocking reason and failure summary derivation
- documentation and tests

Excluded:

- dashboards
- aggregate platform overview pages
- workflow designer or graph editor
- full operations management backend

## Existing Foundation

The current codebase already persists enough workflow-linked runtime data to support this phase:

- `workflow_run_links` stores `tenant_id`, `template_id`, `template_version`, `template_name`, `launch_input`, `launch_metadata`, `effective_workflow_policy`, and `created_at`
- `runs` stores top-level run state
- `agents`, `tasks`, `checkpoints`, and `approval_requests` store execution progress and block conditions
- `events` already supports replay and streaming

This means the phase can be implemented as a read-model and query-surface expansion rather than a runtime rewrite.

## Proposed API Surface

### 1. Tenant Workflow Run List

Purpose:

- list workflow-started runs for a tenant
- provide an operator-readable summary per run
- support triage and filtering before deep inspection

Required query input:

- `tenant_id`

Optional query input:

- `workflow_id`
- `template_version`
- `status`
- `created_after`
- `created_before`
- `cursor`
- `limit`

Returned list item fields:

- `run_id`
- `tenant_id`
- `workflow_id`
- `workflow_name`
- `template_version`
- `status`
- `current_blocking_state`
- `current_blocking_state_reason`
- `latest_failure_summary`
- `latest_checkpoint_step`
- `started_at`
- `last_updated_at`

Pagination:

- cursor-based pagination
- stable ordering by newest workflow-linked runs first
- `limit` constrained to a bounded range consistent with existing API style

### 2. Workflow Run Observation Detail

Purpose:

- provide a single operator-facing observation view for one workflow-started run
- expose enough structured detail to support failure triage without requiring raw event replay first

Route intent:

- detail lookup by `run_id`
- reject non-workflow runs from this API surface

Returned detail sections:

- run summary
- workflow linkage summary
- agent summary
- task summary
- latest checkpoint
- pending approval summary if present
- observation status and blocking reason
- latest failure summary
- event replay linkage information

This API should complement the existing `/v1/runs/{run_id}/events/replay` surface rather than replace it.

## Query and Domain Model

This phase should not mutate the current runtime domain write models. Instead, it should introduce a workflow observability query model layer with clear read responsibilities.

Suggested layered responsibilities:

### Repository Query Layer

Add focused read methods that:

- list workflow-linked runs for a tenant with filters and pagination
- load the raw records needed for a single workflow run observation detail
- preserve existing repository patterns and avoid introducing write-side coupling

### Workflow Observability Service

Add a dedicated service responsible for:

- assembling repository output into stable API-facing query models
- deriving operator-readable observation state
- deriving blocking and failure summaries
- normalizing time semantics such as start and last update timestamps

This service should remain separate from `RunService` and `WorkflowService`. Those services own execution and workflow lifecycle behavior; this new service owns read-model assembly for observability.

### API Schema Layer

Expose stable response models for:

- workflow run list response
- workflow run list items
- workflow run observation detail
- nested approval, task, agent, and checkpoint summaries as needed

The API should not leak repository-specific row shapes.

## Observation State Semantics

This phase should introduce observation states, not replace the underlying runtime states. The goal is to summarize low-level execution records into a clearer operator view.

Recommended derived observation states:

- `running`
- `waiting_for_approval`
- `waiting_on_worker`
- `failed`
- `completed`
- `cancelled`
- `unknown`

Derivation rules:

1. Terminal `run.status` wins first.
   - `completed` -> `completed`
   - `failed` -> `failed`
   - `cancelled` -> `cancelled`

2. Pending approval takes precedence for non-terminal runs.
   - if a run is active and has a pending approval request, derive `waiting_for_approval`

3. Worker wait is next for non-terminal runs.
   - if a supervisor-dispatched task or worker remains in progress and there is no pending approval, derive `waiting_on_worker`

4. Otherwise active runs are `running`.

5. Use `unknown` only when persisted state is inconsistent or insufficient to classify.

## Blocking and Failure Summary Semantics

### Current Blocking State Reason

Return a short operator-facing explanation for why the run is waiting or blocked. Examples:

- `waiting for approval on tool web_search`
- `waiting for dispatched worker result`
- `run still executing without current blocking indicator`

### Latest Failure Summary

Derive the failure summary using this priority order:

1. `run.error`
2. latest failure event payload error
3. latest failure-relevant checkpoint summary

If no failure exists, return `null`.

### Latest Checkpoint Step

Expose the most recent checkpoint `step_name` when present so operators can quickly see where execution paused or failed.

### Pending Approval Summary

If a pending approval exists, include:

- `approval_id`
- `tool_name`
- `reason`
- `created_at`

## Filtering Semantics

The list API should support the following semantics:

- `tenant_id` is required and must reject missing or blank input
- `workflow_id` filters on workflow template identifier
- `template_version` filters on launched workflow version
- `status` filters on top-level run status, not free-form observation reason text
- `created_after` and `created_before` apply to the workflow run link creation timestamp
- cursor and limit behavior should match current workflow list conventions where practical

The filter contract should stay intentionally small in this phase. Do not add free-text search, aggregate buckets, or multi-dimensional dashboard queries yet.

## Data Flow

1. workflow launch persists the existing workflow run link and run state
2. observability list request loads workflow-linked runs for the tenant using repository read methods
3. observability service derives observation state, blocking reason, failure summary, and checkpoint summary
4. API route serializes the stable observability response
5. when deeper investigation is needed, the client calls the existing event replay endpoint for the selected run

## Error Handling

Expected API behaviors:

- missing required tenant input -> `400`
- invalid cursor, limit, or malformed filter input -> `400`
- requesting observation detail for a nonexistent run -> `404`
- requesting observation detail for a run that is not workflow-linked -> `404`

The detail API should intentionally hide non-workflow runs from this workflow observability surface rather than exposing mixed semantics.

## Testing Strategy

### Unit and Service Tests

Cover:

- observation state derivation
- pending approval precedence
- worker-wait classification
- failure summary priority order
- latest checkpoint selection
- cursor and filter validation

### Integration API Tests

Cover:

- tenant workflow run listing
- workflow, version, status, and time-range filtering
- pagination behavior
- detail response shape
- non-workflow run exclusion
- nonexistent run and invalid filter error handling

### Regression Expectations

The new work must not regress:

- `/v1/runs`
- `/v1/workflows`
- `/v1/workflow-templates`

## Delivery Shape

This phase is complete when:

- tenant-scoped workflow run list queries are available
- filtering and pagination are available
- operators can see blocking state and failure summary from list results
- operators can fetch a workflow run observation detail view
- the existing raw event replay path remains available for deeper inspection
- documentation explains field meanings and operational intent

## Deferred Follow-Up

This design intentionally leaves the following for later phases:

- aggregate workflow dashboards
- cross-tenant/global operations views
- visual observability console
- workflow governance and release controls
- tracing integration
- alerting and notification workflows

## Recommendation

Implement this phase as a dedicated workflow observability read-model and API layer. It is the best balance between speed and enterprise-grade extensibility: faster than a full UI initiative, more durable than route-level query glue, and fully aligned with the current API-first architecture.
