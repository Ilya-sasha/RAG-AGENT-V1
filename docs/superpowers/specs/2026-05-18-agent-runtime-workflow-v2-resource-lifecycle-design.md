# Agent Runtime Workflow V2 Resource Lifecycle Design

**Date:** 2026-05-18

**Status:** Draft for review

## 1. Goal

Add the first `workflow v2` phase on top of the completed workflow-template layer so the project can:

- expose a more product-facing workflow resource model without replacing the current runtime kernel
- complete the missing enterprise lifecycle around workflow assets, draft versions, publication, and archival
- provide a recommended `/v1/workflows` API surface while preserving compatibility with `/v1/workflow-templates`
- prepare the system for a later unified workflow resource model and broader API-first workflow platform

This phase is not a visual workflow builder, not a free-form one-shot execution API, and not a new orchestration engine. It is a resource-lifecycle enhancement phase built directly on the current workflow asset implementation.

## 2. Scope

### In Scope

- add a recommended `/v1/workflows` API surface
- keep `/v1/workflow-templates` as a compatibility surface backed by the same data and service logic
- add workflow detail retrieval with latest draft, latest published version, and version summaries
- support creating a new draft version by copying the latest version
- enforce at most one draft version per workflow at a time
- support whole-definition replacement for draft updates
- allow deleting draft versions only
- allow archiving published workflow assets at the workflow header level
- strengthen publish-time validation into a full preflight gate
- extend unit and integration coverage for lifecycle, compatibility, tenant guardrails, and RAG / approval regressions

### Out of Scope

- renaming the underlying persistence model away from the current template-oriented storage in this phase
- visual workflow designer / graph editor
- one-shot external workflow execution from arbitrary request payloads
- arbitrary patch semantics for workflow definitions
- multiple concurrent drafts per workflow
- scheduling, cron, or recurring workflow execution
- tracing implementation

## 3. Key Decisions

### Delivery Shape

- workflow v2 starts by enhancing the existing workflow-template asset instead of introducing a second workflow resource family
- `/v1/workflows` becomes the recommended route family
- `/v1/workflow-templates` remains fully compatible and operates on the same backing records
- the long-term unification into a single outward `workflow` model is deferred to a later cleanup phase

### Lifecycle Strategy

- drafts are the only mutable version state
- published versions remain immutable
- a new version is created by copying the current latest version into a fresh draft
- only one draft may exist per workflow at any given time
- draft updates are full replacements, not partial patches

### Governance Strategy

- unpublished drafts may be deleted
- published versions may not be deleted
- workflows with published history may only be archived, not physically erased through this phase
- publish must run a full preflight gate instead of relying on launch-time failures alone

## 4. Design Principles

- keep the current runtime as the only execution engine
- treat workflow assets as governed enterprise resources with explicit lifecycle rules
- prefer forward-compatible API naming over disruptive storage renames in this phase
- fail before publish when a definition is structurally or tenant-contextually invalid
- preserve compatibility so existing workflow-template callers do not break
- keep the first API-first workflow phase bounded to lifecycle completion, not platform reinvention

## 5. Architecture

### Existing Components To Reuse

- `src/agent_runtime/workflows/repository.py`
- `src/agent_runtime/workflows/service.py`
- `src/agent_runtime/workflows/assembler.py`
- `src/agent_runtime/runtime/services.py`
- `src/agent_runtime/api/routes/workflow_templates.py`

### New Or Expanded Responsibilities

1. `src/agent_runtime/workflows/service.py`
   - becomes the primary workflow asset lifecycle service
   - owns detail assembly, draft-version creation, draft replacement, draft deletion, archive behavior, and publish preflight

2. `src/agent_runtime/workflows/repository.py`
   - adds workflow detail queries and version-summary support
   - adds draft lookup and lifecycle mutation helpers

3. `src/agent_runtime/api/routes/workflows.py`
   - exposes the new recommended `/v1/workflows` route family

4. `src/agent_runtime/api/routes/workflow_templates.py`
   - remains as a compatibility route family
   - reuses the same service behavior where features overlap

5. `src/agent_runtime/api/schemas.py`
   - adds workflow-v2 response and request shapes while keeping compatibility schemas available

### Compatibility Boundary

- new and old routes must operate on the same workflow headers, versions, and run-link records
- the system must not fork into separate `workflow` and `workflow-template` storage models in this phase
- compatibility should be implemented as route- and schema-level adaptation, not duplicate business logic

## 6. Resource Model

### 6.1 Workflow Header

The workflow header remains the stable business-facing identity.

Required conceptual fields:

- `workflow_id`
- `tenant_id`
- `name`
- `description`
- `status`
- `latest_version`
- `latest_published_version`
- `archived_at`
- `created_at`
- `updated_at`

Implementation note:

- this phase may continue storing the identifier in the existing `template_id` field internally
- the new `/v1/workflows` API should expose `workflow_id` as the recommended external name

### 6.2 Workflow Version

Each workflow version stores:

- `workflow_id`
- `version`
- `definition`
- `input_schema`
- `status`
  - `draft`
  - `published`
- `published_at`
- `created_at`
- `created_by`
- `source_version`
  - optional metadata showing which version the draft was copied from

### 6.3 Workflow Detail View

`GET /v1/workflows/{workflow_id}` should return:

- workflow header
- latest draft version in full, if one exists
- latest published version in full, if one exists
- version summary list ordered newest first

This shape is optimized for management UI and operator flows without forcing clients to fetch every version body in one payload.

## 7. Lifecycle Rules

### 7.1 Create Workflow

Creating a workflow:

- creates the workflow header
- creates version `1` as a draft
- validates the initial definition structurally before persistence

### 7.2 Create Draft Version

Creating a new draft version:

- requires that no draft currently exists for the workflow
- copies the latest version definition and input schema into a new draft version
- increments the version number monotonically

### 7.3 Replace Draft Version

Replacing a draft:

- is allowed only for draft versions
- requires a full replacement payload
- reruns structural validation before persistence

### 7.4 Delete Draft Version

Deleting a version:

- is allowed only for draft versions
- is rejected for published versions

### 7.5 Publish Version

Publishing a version:

- is allowed only for a draft version
- requires full preflight success
- makes the version immutable
- updates workflow header publication pointers and status

### 7.6 Archive Workflow

Archiving a workflow:

- acts on the workflow header, not on individual published versions
- is the only allowed offboarding path once published history exists
- does not remove historical versions or run links

## 8. API Surface

### 8.1 Recommended Routes

- `POST /v1/workflows`
- `GET /v1/workflows`
- `GET /v1/workflows/{workflow_id}`
- `POST /v1/workflows/{workflow_id}/versions`
- `PUT /v1/workflows/{workflow_id}/versions/{version}`
- `DELETE /v1/workflows/{workflow_id}/versions/{version}`
- `POST /v1/workflows/{workflow_id}/versions/{version}/publish`
- `POST /v1/workflows/{workflow_id}/archive`
- `POST /v1/workflows/{workflow_id}/launch`

### 8.2 Compatibility Routes

The current `/v1/workflow-templates` family remains available.

Compatibility policy for this phase:

- same data
- same service logic
- no duplicate storage
- no migration requirement for current callers

### 8.3 Naming Strategy

- new routes should prefer `workflow_id`
- compatibility routes may keep current `template_id` naming where required
- internal service methods may keep template-oriented naming temporarily if the logic remains single-sourced

## 9. Publish Preflight

Publish-time validation must aggregate and report all relevant blocking issues that can be checked statically.

At minimum it must validate:

- non-empty `objective_template`
- supported worker roles only
- non-negative execution limits
- no duplicate allowed tools
- no duplicate knowledge-base identifiers
- valid input schema envelope
- draft-only publish eligibility
- tenant policy narrowing rules for workflow tools
- tenant-scoped existence of referenced default knowledge bases
- single-draft lifecycle invariants

Launch-time checks may still exist, but publish should catch the broadest possible set of deterministic failures first.

## 10. Error Model

### `400 Bad Request`

- invalid draft definition
- invalid input schema
- illegal lifecycle operation on the target version

### `404 Not Found`

- workflow not found
- version not found
- cross-tenant access presented as not found

### `409 Conflict`

- workflow already exists
- a draft already exists for the workflow
- version state conflict

### `422 Unprocessable Entity`

- publish preflight failed
- launch guardrails failed
  - unknown knowledge base
  - workflow policy cannot be satisfied

The service layer should use explicit workflow-specific exception types so the API layer can map these consistently.

## 11. Testing Strategy

### Unit Tests

- detail assembly
- create-draft-from-latest copy behavior
- single-draft concurrency rule
- whole-definition replacement on draft update
- draft deletion allowed / published deletion rejected
- archive behavior
- preflight error aggregation
- compatibility naming adapters where needed
- existing-db schema upgrade safety for any new stored fields

### Integration Tests

- create / detail / version / publish / archive / launch workflow lifecycle
- `/v1/workflows` and `/v1/workflow-templates` are backed by the same resources
- cross-tenant list and launch guardrails
- publish preflight rejection behavior
- draft deletion behavior
- approval-gated workflow launch still pauses and resumes correctly
- retrieval-enabled workflow launch still uses `rag_search` with tenant-scoped default KB bindings

### Regression Focus

This phase is not complete unless it proves:

- old workflow-template routes remain functional
- new workflow routes expose the same underlying assets
- workflow launch still uses the normal runtime event path
- approval and RAG behavior remain unchanged under workflow-v2 lifecycle additions

## 12. Deferred Follow-Up

The following remain intentionally deferred beyond this phase:

- one-shot free-form workflow execution payloads
- visual workflow designer / graph editor
- full outward renaming of all internal template-oriented storage and code paths
- tracing integration
- broader workflow platform abstractions such as scheduling and recurring execution

## 13. Completion Criteria

This phase is complete when:

- `/v1/workflows` exists as the recommended route family
- workflow detail and lifecycle operations are implemented
- draft and publish governance rules are enforced
- `/v1/workflow-templates` remains compatible
- focused workflow-v2 tests pass
- full project regression passes
