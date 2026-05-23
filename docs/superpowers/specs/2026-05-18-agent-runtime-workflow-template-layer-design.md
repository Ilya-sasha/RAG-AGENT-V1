# Agent Runtime Workflow Template Layer Design

**Date:** 2026-05-18

**Status:** Draft for review

## 1. Goal

Add a first-generation workflow template layer on top of the existing runtime so the project can:

- define reusable enterprise workflows as governed template assets
- launch runs from published templates instead of hand-written objectives
- bind multi-agent roles, tool policy overlays, approval expectations, and knowledge-base defaults to a named workflow version
- keep execution inside the current event-driven runtime rather than creating a second orchestration engine

This phase is not a generic graph studio, a visual builder, or a full BPM platform. It establishes a stable product-layer surface for repeatable business workflows on top of the current runtime core.

## 2. Scope

### In Scope

- workflow template registration, storage, listing, and versioning
- draft and published workflow template lifecycle
- template input schema and launch-time input validation
- template-scoped runtime configuration for:
  - supervisor objective scaffold
  - allowed worker roles
  - template tool policy narrowing
  - approval expectation metadata
  - default knowledge-base bindings
  - run metadata and execution limits
- launching a run from a published template through an internal API
- durable run-to-template linkage for audit and replay
- integration tests covering template creation, publish, launch, and policy guardrails

### Out of Scope

- visual workflow designer or graph editor
- free-form external workflow execution API that bypasses stored templates
- a new generic DAG execution engine
- dynamic branching DSL beyond what the current runtime can already express through model behavior
- scheduling, cron, or recurring workflow execution
- long-term memory platform features
- tracing implementation

## 3. Key Decisions

### Delivery Shape

- the next product-layer phase is a declarative workflow template asset
- workflow definitions are persisted resources, not one-off request payloads
- execution remains template-driven through internal management APIs
- pure API-first workflow definition and visual design surface are deferred to later phases

### Runtime Strategy

- reuse the existing run lifecycle, orchestrator, tool gateway, approval flow, and retrieval integration
- add a template assembly layer that converts a published template plus launch input into a normal runtime run
- keep the current runtime as the only execution kernel

### Governance Strategy

- template policy may only narrow tenant policy, never broaden it
- template approval requirements are additive relative to tenant policy
- template knowledge-base bindings must stay tenant-scoped and explicit
- published templates are immutable by version

## 4. Design Principles

- workflow templates must be enterprise-governed assets with stable identifiers and versions
- first-generation templates must align with the current runtime instead of forcing a premature graph engine
- template validation should fail early before a run is created
- template launch should produce a normal run so existing events, approvals, and recovery behavior remain valid
- policy composition must be explicit and conservative
- the design should reserve room for later API-first and visual workflow surfaces without breaking template contracts

## 5. Architecture

### Proposed Packages

Create a dedicated `workflows` package with focused responsibilities:

1. `src/agent_runtime/workflows/repository.py`
   Persists workflow templates and template versions.

2. `src/agent_runtime/workflows/service.py`
   Owns template validation, publish rules, listing, and launch-time assembly.

3. `src/agent_runtime/workflows/assembler.py`
   Converts a published template plus launch input into runtime launch artifacts.

4. `src/agent_runtime/api/routes/workflow_templates.py`
   Exposes internal management endpoints for template lifecycle and template-based run launch.

### Existing Integration Points

- `src/agent_runtime/runtime/services.py`
  Gains a template-aware run creation path in addition to the existing raw-objective path.

- `src/agent_runtime/api/schemas.py`
  Gains request and response schemas for workflow template operations.

- `src/agent_runtime/domain/models.py`
  Gains workflow template domain records and template launch metadata records.

- `src/agent_runtime/state/tables.py`
  Gains durable tables for template headers, template versions, and run-template linkage.

### Execution Boundary

The template layer must stop at launch-time assembly.

It may:

- validate template definitions
- validate launch input
- derive the supervisor objective and runtime metadata
- derive template-scoped policy overlays and knowledge defaults

It may not:

- execute steps itself
- replace the current orchestrator
- bypass the tool gateway
- bypass the approval state machine

## 6. Template Model

### 6.1 Workflow Template Header

Represents the stable business-facing workflow identity.

Minimum fields:

- `template_id`
- `tenant_id`
- `name`
- `description`
- `status`
- `latest_version`
- `created_at`
- `updated_at`

### 6.2 Workflow Template Version

Represents an immutable versioned definition for launch.

Minimum fields:

- `template_id`
- `version`
- `definition`
- `input_schema`
- `published_at`
- `created_at`
- `created_by`

`definition` is the canonical stored template payload.

### 6.3 Workflow Definition Shape

The first-generation definition should stay narrow and runtime-aligned.

Minimum sections:

- `entrypoint`
  - `objective_template`
  - `result_contract`

- `agents`
  - `allowed_worker_roles`
  - `max_worker_count`

- `tools`
  - `allowed_tools`
  - `approval_required_tools`

- `knowledge`
  - `default_kb_ids`
  - `allow_kb_override`

- `runtime`
  - `max_turns`
  - `timeout_seconds`
  - `tags`

- `launch_policy`
  - `allow_input_objective_override`
  - `require_published_version`

The first version should not attempt to encode arbitrary node graphs, loops, or conditional branches as first-class template syntax.

### 6.4 Launch Input

Launching a run from a template requires:

- `tenant_id`
- `template_id`
- optional `version`
- `input`
- optional `metadata`

If `version` is omitted, launch uses the latest published version only.

## 7. Launch Semantics

### 7.1 Objective Assembly

The template layer derives the runtime objective from:

1. the published `objective_template`
2. validated launch input
3. template metadata such as workflow name and version

The result is still a plain runtime objective string plus structured metadata attached to the run.

### 7.2 Policy Composition

Effective execution policy is computed as:

- tenant allowed tools intersect template allowed tools
- approval-required tools are the union of tenant and template approval requirements
- template worker roles must stay within predefined runtime-supported roles
- knowledge-base bindings must belong to the same tenant

If the effective policy becomes invalid, launch fails before a run is created.

### 7.3 Run Linkage

Every template-launched run must store:

- `template_id`
- `template_version`
- `template_name`
- `launch_input`
- `effective_workflow_policy`

This keeps audit, replay, and operator inspection aligned with the business workflow that created the run.

## 8. API Surface

### Internal Management Endpoints

The first-generation API should include:

- `POST /v1/workflow-templates`
  create a template header and initial draft version

- `GET /v1/workflow-templates`
  list templates for a tenant

- `GET /v1/workflow-templates/{template_id}`
  return template header plus available versions

- `POST /v1/workflow-templates/{template_id}/versions`
  create a new draft version

- `POST /v1/workflow-templates/{template_id}/versions/{version}/publish`
  publish an immutable version

- `POST /v1/workflow-templates/{template_id}/launch`
  launch a run from a published template

### API Behavior Rules

- launch is rejected for draft-only templates
- publish is rejected if the definition is invalid
- template lookup is tenant-scoped
- version numbers are monotonic per template
- launch returns the normal run response shape plus template linkage metadata

## 9. Validation Rules

At minimum, template validation must enforce:

- `template_id` uniqueness within tenant scope
- non-empty `objective_template`
- supported worker roles only
- non-negative execution limits
- no duplicate tool names or knowledge-base identifiers
- template tools cannot exceed tenant policy at launch time
- knowledge-base identifiers referenced by template launch must exist for the tenant
- published definitions are immutable

Validation should happen in two layers:

1. structural validation at create/update/publish time
2. tenant-aware policy validation at launch time

## 10. Error Handling

The workflow template layer should introduce explicit error classes or stable error codes for:

- invalid template definition
- unpublished template launch
- tenant mismatch
- unknown knowledge base
- unsupported worker role
- empty effective tool policy
- invalid launch input

Launch failure before run creation must not emit partial run state.

## 11. Testing Strategy

### Unit Tests

- template definition validation
- objective assembly behavior
- tool policy intersection and approval union
- template version immutability rules

### Integration Tests

- create, publish, and list template lifecycle
- launch from published template creates a normal run
- template launch links run to template version
- tenant guardrails on template access and launch
- knowledge-base binding validation during launch

### Regression Focus

The first workflow template phase is not complete unless it proves:

- template-launched runs still use the normal runtime event path
- approval-gated tools still pause and resume correctly
- retrieval-enabled workflows can carry default knowledge-base bindings without bypassing `rag_search`

## 12. Deferred Follow-Up

The following items are intentionally deferred beyond this phase:

- free-form workflow definition execution through pure external API payloads
- visual workflow designer and graph editor
- richer branching DSL and graph semantics
- scheduled workflow execution
- tracing
- long-term memory integration

## 13. Recommendation

The recommended first implementation is a template-driven run launcher, not a workflow graph engine.

That gives the project an enterprise-usable application layer quickly while preserving the current kernel, governance model, recovery path, and RAG integration. It also creates the right substrate for a later API-first execution surface and a visual designer without forcing either one into the first release.
