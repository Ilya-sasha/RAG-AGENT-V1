# Agent Runtime Workflow Management Query API Design

**Date:** 2026-05-18

**Status:** Draft for review

## 1. Goal

Add the first management-oriented query surface on top of the completed `workflow v2` lifecycle layer so the project can:

- support a backend-facing workflow list view for operators and platform administrators
- let callers locate workflow assets through stable query semantics instead of fetching individual workflows one by one
- keep the new query behavior inside the existing `/v1/workflows` outward surface rather than creating a second admin-only route family
- establish the first bounded step toward a broader API-first workflow platform without expanding into execution-surface redesign yet

This phase is not a workflow detail expansion, not a version-browser phase, not a run-history phase, and not an execution-API enhancement phase. It is a deliberately narrow query phase focused on making workflow assets discoverable and manageable in backend list views.

## 2. Scope

### In Scope

- add a lightweight `GET /v1/workflows` list endpoint for backend-oriented workflow discovery
- support tenant-scoped querying only
- support first-phase query filters:
  - `workflow_id_prefix`
  - `name_query`
- support cursor pagination
- use a stable default ordering:
  - `created_at desc`
  - `workflow_id asc`
- return a lightweight summary shape:
  - `workflow_id`
  - `tenant_id`
  - `name`
  - `status`
  - `latest_version`
- return `items + next_cursor` only
- extend repository, service, route, schema, and test coverage required for the new list query behavior

### Out of Scope

- workflow detail-page expansion beyond the existing detail endpoint
- version-browser APIs or richer version-history views
- lifecycle-status filters such as `has_draft`, `has_published`, or `archived`
- operations filters such as `created_by`, `updated_at`, `published_at`, or `archived_at`
- `description` search
- total counts, matched counts, or list-level aggregate statistics
- page-number pagination
- admin-only parallel route families such as `/v1/workflow-admin/*`
- execution-surface enhancements such as broader launch or one-shot execution APIs
- run-history, audit, or governance query expansion

## 3. Key Decisions

### Delivery Shape

- keep `/v1/workflows` as the only outward workflow route family for the new list API
- do not introduce a separate admin resource family in this phase
- keep the list response intentionally lightweight so details remain the responsibility of the existing single-resource endpoints

### Query Strategy

- `workflow_id_prefix` supports exact or prefix matching through a single parameter
- `name_query` supports case-insensitive fuzzy matching against workflow `name`
- when both filters are present, query semantics use `AND`
- `description` is intentionally excluded from first-phase search

### Pagination Strategy

- cursor pagination is preferred over page-number or raw offset pagination
- the cursor is opaque to API clients
- the cursor internally anchors on the list sort keys:
  - `created_at`
  - `workflow_id`
- list reads use `limit + 1` fetch semantics to determine whether a next page exists

### Platform-Boundary Strategy

- keep all workflow query behavior on top of the existing workflow-header storage model
- do not fork storage or duplicate workflow data for query-only use cases
- do not turn this list phase into a broader workflow-platform redesign

## 4. Design Principles

- keep the phase narrowly focused on list discovery
- prefer stable and conservative query semantics over broad first-phase capability
- preserve the current workflow-v2 resource model and same-data compatibility guarantees
- make the list endpoint useful for backend screens without inflating it into a summary-detail hybrid
- keep response shapes small enough that later detail, version, and governance phases can evolve independently

## 5. Architecture

### Existing Components To Reuse

- `src/agent_runtime/workflows/repository.py`
- `src/agent_runtime/workflows/service.py`
- `src/agent_runtime/api/routes/workflows.py`
- `src/agent_runtime/api/schemas.py`

### New Or Expanded Responsibilities

1. `src/agent_runtime/workflows/repository.py`
   - adds the workflow-header list query helper
   - owns filter application, stable ordering, cursor decode/encode support, and `limit + 1` fetch behavior

2. `src/agent_runtime/workflows/service.py`
   - exposes a thin list-query service method
   - validates list query inputs where appropriate
   - delegates all persistence-query semantics to the repository

3. `src/agent_runtime/api/routes/workflows.py`
   - exposes `GET /v1/workflows`
   - parses query parameters
   - returns stable workflow list responses

4. `src/agent_runtime/api/schemas.py`
   - adds the request/response models required for the list endpoint

### Explicit Non-Responsibilities For This Phase

- repository does not add run-history joins
- service does not perform manual filtering in Python after broad reads
- route does not branch into separate backend and public variants
- schema does not add summary statistics or detail payloads to list items

## 6. API Surface

### 6.1 Endpoint

- `GET /v1/workflows`

### 6.2 Request Parameters

- `tenant_id`
  - required
- `workflow_id_prefix`
  - optional
  - exact match is handled as the prefix special case
- `name_query`
  - optional
  - case-insensitive fuzzy match on workflow `name`
- `cursor`
  - optional
  - opaque pagination token
- `limit`
  - optional
  - bounded positive integer with a default and an upper limit

### 6.3 Response Shape

```json
{
  "items": [
    {
      "workflow_id": "wf-triage",
      "tenant_id": "tenant-a",
      "name": "Incident Triage",
      "status": "published",
      "latest_version": 3
    }
  ],
  "next_cursor": "opaque-token"
}
```

### 6.4 Lightweight Summary Contract

Each item returns only:

- `workflow_id`
- `tenant_id`
- `name`
- `status`
- `latest_version`

The following fields are intentionally excluded from list items in this phase:

- `description`
- `latest_published_version`
- `archived_at`
- `created_at`
- `updated_at`
- version summaries
- latest draft body
- latest published body
- run counts or execution statistics

## 7. Query Semantics

### 7.1 Tenant Guardrail

- every query is tenant-scoped
- cross-tenant list visibility remains disallowed
- tenant scope is mandatory and not inferred from cursor contents alone

### 7.2 Workflow Identifier Filter

- `workflow_id_prefix` matches workflow identifiers by prefix
- exact-match use cases do not need a separate parameter

### 7.3 Name Filter

- `name_query` matches on workflow `name` only
- matching is case-insensitive
- matching is fuzzy enough for backend search convenience, but bounded to a single field

### 7.4 Combined Filtering

- if both `workflow_id_prefix` and `name_query` are present, both constraints must hold
- no `OR` semantics are introduced in this phase

## 8. Cursor Design

### 8.1 Sort Keys

The canonical list order is:

1. `created_at desc`
2. `workflow_id asc`

### 8.2 Cursor Contents

The cursor remains opaque externally, but internally it must carry enough information to resume after the last visible record:

- anchor `created_at`
- anchor `workflow_id`

### 8.3 Page Construction

- fetch `limit + 1`
- if more than `limit` rows are returned:
  - trim the final row from `items`
  - generate `next_cursor` from the last visible row
- if `limit + 1` rows are not returned:
  - return all rows
  - set `next_cursor = null`

### 8.4 Stability Rules

- no duplicate items across adjacent pages
- no dropped items across adjacent pages
- cursor decoding errors must fail fast rather than silently degrading to page one

## 9. Error Handling

### 9.1 Validation Failures

Return `400` for:

- missing `tenant_id`
- invalid `limit`
- limit above the configured upper bound
- malformed or incompatible cursor payload

### 9.2 Empty Results

Empty result sets are not errors.

Return `200` with:

- `items = []`
- `next_cursor = null`

### 9.3 Not Found Semantics

List queries do not emit `404` when no workflows match.

## 10. Testing Strategy

### Repository Tests

- tenant isolation
- `workflow_id_prefix` filtering
- `name_query` filtering
- combined filtering
- stable ordering on `created_at desc, workflow_id asc`
- cursor pagination continuity with no duplicates or gaps

### Service Tests

- lightweight parameter validation
- passthrough to repository list semantics
- no mutation of repository ordering/filter behavior

### Integration Tests

- `GET /v1/workflows` happy path
- empty results
- invalid cursor
- limit boundary handling
- tenant guardrails
- no regression to existing `/v1/workflows/{workflow_id}` and `/v1/workflow-templates` lifecycle behavior

## 11. Deferred Follow-Up

The following remain intentionally deferred beyond this phase:

- lifecycle-status filters such as `draft`, `published`, `archived`, `has_draft`, and `has_published`
- operations filters such as `created_by`, `updated_at`, `published_at`, and `archived_at`
- workflow detail-page expansion
- version-browser views
- workflow-to-run history views
- workflow governance and audit query APIs
- execution-surface enhancement beyond the current launch behavior
- description search
- total-count or aggregate-statistics responses

## 12. Completion Criteria

This phase is complete when:

- `GET /v1/workflows` exists as a tenant-scoped list query endpoint
- the list supports `workflow_id_prefix`, `name_query`, `cursor`, and `limit`
- list responses return lightweight items plus `next_cursor`
- the canonical ordering is `created_at desc, workflow_id asc`
- cursor pagination is stable across pages
- focused tests for the new list behavior pass
- full project regression still passes
