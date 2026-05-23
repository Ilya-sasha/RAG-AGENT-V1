# Agent Runtime Workflow Detail Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand workflow detail responses to expose `created_at` and `updated_at` on both `/v1/workflows/{workflow_id}` and `/v1/workflow-templates/{template_id}` while preserving existing compatibility behavior.

**Architecture:** This phase stays at the API-detail layer. Existing workflow header records already carry `created_at` and `updated_at`, so no repository or service changes are needed. The work is limited to response schemas, route serialization, and integration coverage for both outward route families.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest, pytest-asyncio

---

## File Structure

### Modified Files

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
  Extend `WorkflowDetailResponse` and `WorkflowTemplateDetailResponse` with top-level `created_at` and `updated_at`.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflows.py`
  Include `created_at` and `updated_at` when building workflow detail responses and keep current detail/list/lifecycle behavior unchanged.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_templates.py`
  Include matching metadata in compatibility detail responses and keep current compatibility route behavior unchanged.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
  Update workflow-detail assertions to require `created_at` and `updated_at`, plus verify compatibility metadata remains aligned.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`
  Update compatibility-detail assertions to require `created_at` and `updated_at`.

### Verification Commands

- Focused workflow route integration:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflows_api.py -v`

- Focused workflow-template integration:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_templates_api.py -v`

- Workflow-focused regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`

- Full regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`

### Task 1: Add Red Integration Coverage For Detail Metadata Expansion

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`

- [ ] **Step 1: Update workflow detail integration expectations to require `created_at` and `updated_at`**

```python
detail_response = await client.get(
    "/v1/workflows/wf-triage",
    params={"tenant_id": "tenant-a"},
)
assert detail_response.status_code == 200
detail_payload = detail_response.json()
assert detail_payload["workflow_id"] == "wf-triage"
assert detail_payload["created_at"] is not None
assert detail_payload["updated_at"] is not None
assert detail_payload["archived_at"] is None
assert detail_payload["latest_draft"]["version"] == 1
```

- [ ] **Step 2: Strengthen compatibility assertions in the workflow route test**

```python
compatibility_detail_response = await client.get(
    "/v1/workflow-templates/wf-triage",
    params={"tenant_id": "tenant-a"},
)
assert compatibility_detail_response.status_code == 200
compatibility_detail_payload = compatibility_detail_response.json()
assert compatibility_detail_payload["created_at"] == detail_payload["created_at"]
assert compatibility_detail_payload["updated_at"] == detail_payload["updated_at"]
assert compatibility_detail_payload["archived_at"] == archive_payload["archived_at"]
```

- [ ] **Step 3: Update workflow-template compatibility detail expectations to require `created_at` and `updated_at`**

```python
detail_response = await client.get(
    "/v1/workflow-templates/wf-triage",
    params={"tenant_id": "tenant-a"},
)
assert detail_response.status_code == 200
detail_payload = detail_response.json()
assert detail_payload["template_id"] == "wf-triage"
assert detail_payload["created_at"] is not None
assert detail_payload["updated_at"] is not None
assert detail_payload["archived_at"] is None
```

- [ ] **Step 4: Run focused integration suites to verify the new assertions fail before implementation**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`
Expected: FAIL because detail response models and route serialization do not yet expose `created_at` / `updated_at`.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_workflows_api.py tests/integration/test_workflow_templates_api.py
git commit -m "test: add workflow detail metadata coverage"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 2: Extend Detail Response Schemas And Route Serialization

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflows.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_templates.py`

- [ ] **Step 1: Extend workflow detail schemas with top-level `created_at` and `updated_at`**

```python
class WorkflowDetailResponse(WorkflowResponse):
    created_at: datetime
    updated_at: datetime
    latest_draft: WorkflowVersionResponse | None = None
    latest_published: WorkflowVersionResponse | None = None
    version_summaries: list[WorkflowVersionSummaryResponse] = Field(default_factory=list)


class WorkflowTemplateDetailResponse(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int
    latest_published_version: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    latest_draft: WorkflowTemplateVersionResponse | None = None
    latest_published: WorkflowTemplateVersionResponse | None = None
    version_summaries: list[WorkflowTemplateVersionSummaryResponse] = Field(default_factory=list)
```

- [ ] **Step 2: Make workflow detail serialization include the new metadata**

```python
def _serialize_workflow(template) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=template.template_id,
        tenant_id=template.tenant_id,
        name=template.name,
        description=template.description,
        status=template.status,
        latest_version=template.latest_version,
        latest_published_version=template.latest_published_version,
        archived_at=template.archived_at,
    )


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow_detail(...) -> WorkflowDetailResponse:
    ...
    return WorkflowDetailResponse(
        **_serialize_workflow(detail["template"]).model_dump(),
        created_at=detail["template"].created_at,
        updated_at=detail["template"].updated_at,
        latest_draft=(...),
        latest_published=(...),
        version_summaries=[...],
    )
```

- [ ] **Step 3: Make compatibility detail serialization include matching metadata**

```python
def _serialize_workflow_template_lifecycle(template) -> WorkflowTemplateLifecycleResponse:
    return WorkflowTemplateLifecycleResponse(
        template_id=template.template_id,
        tenant_id=template.tenant_id,
        name=template.name,
        description=template.description,
        status=template.status,
        latest_version=template.latest_version,
        latest_published_version=template.latest_published_version,
        archived_at=template.archived_at,
    )


@router.get("/{template_id}", response_model=WorkflowTemplateDetailResponse)
async def get_workflow_template_detail(...) -> WorkflowTemplateDetailResponse:
    ...
    return WorkflowTemplateDetailResponse(
        **_serialize_workflow_template_lifecycle(detail["template"]).model_dump(),
        created_at=detail["template"].created_at,
        updated_at=detail["template"].updated_at,
        latest_draft=(...),
        latest_published=(...),
        version_summaries=[...],
    )
```

- [ ] **Step 4: Run focused integration suites to verify both route families now pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`
Expected: PASS with `created_at` / `updated_at` present on both detail endpoints and compatibility assertions remaining green.

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api/schemas.py src/agent_runtime/api/routes/workflows.py src/agent_runtime/api/routes/workflow_templates.py tests/integration/test_workflows_api.py tests/integration/test_workflow_templates_api.py
git commit -m "feat: add workflow detail metadata fields"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 3: Run Workflow-Focused Verification And Final No-Regression Checks

**Files:**
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`

- [ ] **Step 1: Run workflow-focused regression**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`
Expected: PASS with no regression to list-query behavior, lifecycle routes, or template compatibility coverage.

- [ ] **Step 2: Re-check spec alignment for this phase**

Run: `rg -n "created_at|updated_at|archived_at|workflow-templates|version-browser|launch-readiness" docs/superpowers/specs/2026-05-18-agent-runtime-workflow-detail-metadata-design.md`
Expected: the spec remains narrowly scoped to detail metadata expansion and explicitly defers version-browser and launch-readiness work.

- [ ] **Step 3: Run the full regression suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_workflows_api.py tests/integration/test_workflow_templates_api.py src/agent_runtime/api/schemas.py src/agent_runtime/api/routes/workflows.py src/agent_runtime/api/routes/workflow_templates.py
git commit -m "test: verify workflow detail metadata expansion"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Self-Review

- Spec coverage:
  - add `created_at` / `updated_at` to `/v1/workflows/{workflow_id}`: Tasks 1 and 2
  - add matching metadata to `/v1/workflow-templates/{template_id}`: Tasks 1 and 2
  - preserve `archived_at` behavior: Tasks 1, 2, and 3
  - keep scope out of version-browser / launch-readiness work: Task 3
  - preserve full regression health: Task 3

- Placeholder scan:
  - all tasks include exact file paths, concrete assertions, commands, and expected outcomes
  - commit steps are preserved for workflow parity and explicitly marked non-executable unless later requested

- Type consistency:
  - `WorkflowDetailResponse` uses `workflow_id`, while `WorkflowTemplateDetailResponse` keeps `template_id`
  - both detail response models add `created_at` and `updated_at` as top-level `datetime` fields
  - route code continues to rely on `detail["template"]` from the existing service detail contract
