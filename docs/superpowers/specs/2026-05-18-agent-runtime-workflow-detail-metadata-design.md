# Agent Runtime Workflow Detail Metadata Design

**Date:** 2026-05-18

**Status:** Draft for review

## 1. Goal

Add the next bounded workflow-management read enhancement after the completed list-query phase by expanding workflow detail responses with minimal header metadata needed by a backend detail page.

This phase is intentionally narrow:

- keep the current workflow detail endpoints
- add only header-level metadata fields
- preserve compatibility between `/v1/workflows/{workflow_id}` and `/v1/workflow-templates/{template_id}`
- avoid turning this into version-browser work or launch-readiness analysis

## 2. Scope

### In Scope

- expand `GET /v1/workflows/{workflow_id}`
- expand `GET /v1/workflow-templates/{template_id}`
- expose `created_at` and `updated_at` at the top level of both detail responses
- preserve existing `archived_at` behavior
- keep existing latest-draft, latest-published, and version-summary sections intact
- add tests that verify both route families return the new metadata consistently
- keep implementation aligned with current workflow-v2 storage and service boundaries

### Out of Scope

- version-browser views
- version diffing
- extra version metadata such as published timestamps or draft authors in top-level detail headers
- launch-readiness / preflight summary fields
- workflow-to-run history
- governance / audit reads
- list endpoint changes
- write-path changes for workflow create / publish / archive / launch

## 3. Key Decisions

### Delivery Shape

- keep the current detail endpoints rather than introducing a new admin-only detail route
- keep `workflow` and `workflow-template` detail responses behaviorally aligned
- continue using top-level detail fields instead of introducing a nested `metadata` object in this phase

### Metadata Scope

- `archived_at` remains as-is
- `created_at` is newly exposed
- `updated_at` is newly exposed
- no additional header metadata is added in this phase

### Compatibility Strategy

- `/v1/workflows/{workflow_id}` remains the main outward workflow detail route
- `/v1/workflow-templates/{template_id}` continues to expose matching detail metadata for compatibility
- the phase should avoid semantic drift between the two route families

## 4. Architecture

### Existing Components To Reuse

- `src/agent_runtime/workflows/service.py`
- `src/agent_runtime/api/schemas.py`
- `src/agent_runtime/api/routes/workflows.py`
- `src/agent_runtime/api/routes/workflow_templates.py`

### Expanded Responsibilities

1. `src/agent_runtime/api/schemas.py`
   - extend workflow detail response models with `created_at` and `updated_at`

2. `src/agent_runtime/api/routes/workflows.py`
   - include the new metadata fields when serializing workflow detail responses
   - keep existing list, lifecycle, and launch behavior unchanged

3. `src/agent_runtime/api/routes/workflow_templates.py`
   - include the same metadata fields in compatibility detail responses
   - preserve current compatibility route behavior outside the added fields

4. `tests/integration/test_workflows_api.py`
   - verify workflow detail metadata exposure through `/v1/workflows/{workflow_id}`

5. `tests/integration/test_workflow_templates_api.py`
   - verify compatibility detail metadata exposure through `/v1/workflow-templates/{template_id}`

### Explicit Non-Responsibilities

- service does not need a new detail method for this phase
- repository does not need new queries or schema changes for this phase
- no new persistence columns are introduced
- no list-response fields are added

## 5. API Surface

### 5.1 Expanded Workflow Detail Response

`GET /v1/workflows/{workflow_id}`

The existing response shape remains, with two added top-level fields:

- `created_at`
- `updated_at`

Example:

```json
{
  "workflow_id": "wf-triage",
  "tenant_id": "tenant-a",
  "name": "Incident Triage",
  "description": "Triage incidents with lifecycle routes",
  "status": "draft",
  "latest_version": 2,
  "latest_published_version": 1,
  "created_at": "2026-05-18T08:00:00Z",
  "updated_at": "2026-05-18T08:15:00Z",
  "archived_at": null,
  "latest_draft": {},
  "latest_published": {},
  "version_summaries": []
}
```

### 5.2 Expanded Compatibility Detail Response

`GET /v1/workflow-templates/{template_id}`

The compatibility response adds the same two top-level fields:

- `created_at`
- `updated_at`

It continues to expose the compatibility naming surface such as `template_id`.

## 6. Data Semantics

### 6.1 `created_at`

- sourced from the workflow header record
- represents workflow header creation time
- does not change when later versions are created

### 6.2 `updated_at`

- sourced from the workflow header record
- reflects the last workflow-header lifecycle mutation already persisted by existing behavior
- may change when publish / archive / draft-version lifecycle actions update the header

### 6.3 `archived_at`

- remains unchanged in meaning and placement
- is not reworked in this phase

## 7. Error Handling

- no new error classes are introduced
- existing not-found and validation behavior remains unchanged
- metadata expansion must not alter current `404` / `400` route behavior

## 8. Testing Strategy

### Integration Tests

- verify `/v1/workflows/{workflow_id}` returns `created_at`, `updated_at`, and `archived_at`
- verify `/v1/workflow-templates/{template_id}` returns `created_at`, `updated_at`, and `archived_at`
- verify both route families expose matching metadata values for the same workflow resource
- verify existing lifecycle/detail compatibility assertions remain green after the response expansion

### Regression Guardrails

- no regression to workflow list-query behavior
- no regression to workflow version lifecycle routes
- no regression to template compatibility routes outside the new metadata fields

## 9. Deferred Follow-Up

The following remain intentionally deferred beyond this phase:

- richer version-browser detail
- published-at and created-by header expansion
- launch-readiness summary
- workflow-to-run detail associations
- governance and audit views
- nested metadata blocks or response reshaping

## 10. Completion Criteria

This phase is complete when:

- both workflow detail route families expose `created_at` and `updated_at`
- existing `archived_at` behavior is preserved
- both route families remain metadata-consistent for the same workflow
- focused integration tests for both route families pass
- full project regression still passes
