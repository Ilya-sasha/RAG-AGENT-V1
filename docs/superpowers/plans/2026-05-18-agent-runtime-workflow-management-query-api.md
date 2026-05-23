# Agent Runtime Workflow Management Query API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first backend-oriented workflow management query API by turning `GET /v1/workflows` into a lightweight, tenant-scoped, cursor-paginated workflow list endpoint with `workflow_id_prefix` and `name_query` filtering.

**Architecture:** This phase extends the existing workflow-v2 stack in place instead of introducing a new admin route family or storage model. The repository owns filter and cursor semantics, the workflow service exposes a thin list-query method, and the route layer adapts the result into a lightweight `items + next_cursor` response while leaving existing detail and lifecycle endpoints intact.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite, pytest, pytest-asyncio

---

## File Structure

### Modified Files

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
  Add tenant-scoped workflow-header list query logic, cursor encode/decode helpers, and stable `created_at desc, workflow_id asc` ordering.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\service.py`
  Add a thin workflow list-query service method plus list-query input validation.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
  Add lightweight workflow list item / list response schemas for the new list contract.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflows.py`
  Change `GET /v1/workflows` from full-resource list output to the new list-query contract and map invalid list inputs to `400`.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
  Add repository and service coverage for workflow list filtering, pagination, and input validation.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
  Update existing workflow list expectations and add route-level coverage for cursor pagination, filtering, invalid cursor, and tenant guardrails.

### Verification Commands

- Focused unit suite:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`

- Focused workflow integration suite:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflows_api.py -v`

- Full workflow-focused verification:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`

- Full regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`

### Task 1: Add Red Unit Tests For Workflow Management Query Semantics

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`

- [ ] **Step 1: Add failing repository tests for prefix filter, fuzzy name filter, and cursor pagination**

```python
@pytest.mark.asyncio
async def test_workflow_repository_list_workflow_summaries_filters_and_paginates(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-gamma",
                tenant_id="tenant-a",
                name="Gamma Workflow",
                description="third",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-gamma",
                version=1,
                definition={"entrypoint": {"objective_template": "Gamma"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-beta",
                tenant_id="tenant-a",
                name="Beta Workflow",
                description="second",
                status="published",
                latest_version=2,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-beta",
                version=2,
                definition={"entrypoint": {"objective_template": "Beta"}},
                input_schema={"type": "object"},
                is_published=True,
                created_by="operator-b",
            ),
        )
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="ops-alpha",
                tenant_id="tenant-a",
                name="Alpha Incident Flow",
                description="first",
                status="archived",
                latest_version=3,
            ),
            WorkflowTemplateVersionRecord(
                template_id="ops-alpha",
                version=3,
                definition={"entrypoint": {"objective_template": "Alpha"}},
                input_schema={"type": "object"},
                is_published=True,
                created_by="operator-c",
            ),
        )

        first_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-",
            name_query="workflow",
            limit=1,
            cursor=None,
        )

        assert [item["workflow_id"] for item in first_page["items"]] == ["wf-beta"]
        assert first_page["next_cursor"] is not None

        second_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-",
            name_query="workflow",
            limit=1,
            cursor=first_page["next_cursor"],
        )

        assert [item["workflow_id"] for item in second_page["items"]] == ["wf-gamma"]
        assert second_page["next_cursor"] is None
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 2: Add failing repository test for tenant isolation and malformed cursor handling**

```python
@pytest.mark.asyncio
async def test_workflow_repository_list_workflow_summaries_is_tenant_scoped_and_rejects_bad_cursor(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-tenant-a",
                tenant_id="tenant-a",
                name="Tenant A Flow",
                description="a",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-tenant-a",
                version=1,
                definition={"entrypoint": {"objective_template": "A"}},
                input_schema={"type": "object"},
            ),
        )
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-tenant-b",
                tenant_id="tenant-b",
                name="Tenant B Flow",
                description="b",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-tenant-b",
                version=1,
                definition={"entrypoint": {"objective_template": "B"}},
                input_schema={"type": "object"},
            ),
        )

        tenant_a_page = await workflow_repository.list_workflow_summaries(
            tenant_id="tenant-a",
            workflow_id_prefix=None,
            name_query=None,
            limit=10,
            cursor=None,
        )

        assert [item["workflow_id"] for item in tenant_a_page["items"]] == ["wf-tenant-a"]

        with pytest.raises(ValueError, match="invalid workflow list cursor"):
            await workflow_repository.list_workflow_summaries(
                tenant_id="tenant-a",
                workflow_id_prefix=None,
                name_query=None,
                limit=10,
                cursor="not-a-valid-cursor",
            )
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 3: Add failing service test for limit validation and passthrough behavior**

```python
@pytest.mark.asyncio
async def test_workflow_service_list_workflows_validates_limit_and_returns_items_plus_next_cursor(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-summary",
                tenant_id="tenant-a",
                name="Summary Workflow",
                description="summary",
                status="draft",
                latest_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-summary",
                version=1,
                definition={"entrypoint": {"objective_template": "Summary"}},
                input_schema={"type": "object"},
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplateValidationError, match="limit must be between 1 and 100"):
            await service.list_workflows(
                tenant_id="tenant-a",
                workflow_id_prefix=None,
                name_query=None,
                limit=0,
                cursor=None,
            )

        result = await service.list_workflows(
            tenant_id="tenant-a",
            workflow_id_prefix="wf-",
            name_query="summary",
            limit=10,
            cursor=None,
        )

        assert [item["workflow_id"] for item in result["items"]] == ["wf-summary"]
        assert result["next_cursor"] is None
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 4: Run the focused unit suite to verify the new tests fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: FAIL with missing `list_workflow_summaries(...)`, missing `list_workflows(...)`, or missing cursor validation logic.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_workflow_service.py
git commit -m "test: add workflow management query red tests"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 2: Implement Repository Cursor Query And Service Wrapper

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\service.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`

- [ ] **Step 1: Add repository cursor constants and encode/decode helpers**

```python
import base64
import json
from datetime import UTC, datetime

WORKFLOW_LIST_LIMIT_DEFAULT = 20
WORKFLOW_LIST_LIMIT_MAX = 100


def _encode_workflow_list_cursor(*, created_at: datetime, workflow_id: str) -> str:
    payload = {
        "created_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "workflow_id": workflow_id,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _decode_workflow_list_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00")).astimezone(UTC)
        workflow_id = payload["workflow_id"]
    except Exception as exc:
        raise ValueError("invalid workflow list cursor") from exc
    if not isinstance(workflow_id, str) or not workflow_id:
        raise ValueError("invalid workflow list cursor")
    return created_at, workflow_id
```

- [ ] **Step 2: Add repository list query helper with tenant scope, filters, sorting, and `limit + 1` paging**

```python
from sqlalchemy import and_, or_, select


async def list_workflow_summaries(
    self,
    *,
    tenant_id: str,
    workflow_id_prefix: str | None,
    name_query: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, object]:
    async with self._session_factory() as session:
        statement = select(WorkflowTemplateTable).where(WorkflowTemplateTable.tenant_id == tenant_id)

        if workflow_id_prefix:
            statement = statement.where(WorkflowTemplateTable.template_id.like(f"{workflow_id_prefix}%"))
        if name_query:
            statement = statement.where(WorkflowTemplateTable.name.ilike(f"%{name_query}%"))

        if cursor is not None:
            anchor_created_at, anchor_workflow_id = _decode_workflow_list_cursor(cursor)
            statement = statement.where(
                or_(
                    WorkflowTemplateTable.created_at < anchor_created_at,
                    and_(
                        WorkflowTemplateTable.created_at == anchor_created_at,
                        WorkflowTemplateTable.template_id > anchor_workflow_id,
                    ),
                )
            )

        rows = (
            await session.execute(
                statement.order_by(
                    WorkflowTemplateTable.created_at.desc(),
                    WorkflowTemplateTable.template_id.asc(),
                ).limit(limit + 1)
            )
        ).scalars().all()

        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        next_cursor = (
            _encode_workflow_list_cursor(
                created_at=visible_rows[-1].created_at,
                workflow_id=visible_rows[-1].template_id,
            )
            if has_more and visible_rows
            else None
        )

        return {
            "items": [
                {
                    "workflow_id": row.template_id,
                    "tenant_id": row.tenant_id,
                    "name": row.name,
                    "status": row.status,
                    "latest_version": row.latest_version,
                }
                for row in visible_rows
            ],
            "next_cursor": next_cursor,
        }
```

- [ ] **Step 3: Add service wrapper and limit validation without changing existing detail/lifecycle behavior**

```python
WORKFLOW_LIST_LIMIT_DEFAULT = 20
WORKFLOW_LIST_LIMIT_MAX = 100


async def list_workflows(
    self,
    *,
    tenant_id: str,
    workflow_id_prefix: str | None,
    name_query: str | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, object]:
    effective_limit = WORKFLOW_LIST_LIMIT_DEFAULT if limit is None else limit
    if effective_limit < 1 or effective_limit > WORKFLOW_LIST_LIMIT_MAX:
        raise WorkflowTemplateValidationError("limit must be between 1 and 100")
    return await self._repository.list_workflow_summaries(
        tenant_id=tenant_id,
        workflow_id_prefix=workflow_id_prefix,
        name_query=name_query,
        limit=effective_limit,
        cursor=cursor,
    )
```

- [ ] **Step 4: Run the focused unit suite to verify repository and service list behavior passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: PASS for workflow list query coverage with no regression to existing workflow lifecycle tests.

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/workflows/repository.py src/agent_runtime/workflows/service.py tests/unit/test_workflow_service.py
git commit -m "feat: add workflow management query repository"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 3: Add List Schemas And Route Contract For `GET /v1/workflows`

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflows.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`

- [ ] **Step 1: Add failing integration coverage for lightweight list output, filtering, pagination, and invalid cursor**

```python
@pytest.mark.asyncio
async def test_workflow_routes_list_query_supports_filters_cursor_and_lightweight_items(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        for workflow_id, name in (
            ("wf-gamma", "Gamma Workflow"),
            ("wf-beta", "Beta Workflow"),
            ("ops-alpha", "Alpha Incident Flow"),
        ):
            create_response = await client.post(
                "/v1/workflows",
                json={
                    "workflow_id": workflow_id,
                    "tenant_id": "tenant-a",
                    "name": name,
                    "description": f"description for {workflow_id}",
                    "definition": _workflow_definition(),
                    "input_schema": _workflow_input_schema(),
                },
            )
            assert create_response.status_code == 201

        first_page = await client.get(
            "/v1/workflows",
            params={
                "tenant_id": "tenant-a",
                "workflow_id_prefix": "wf-",
                "name_query": "workflow",
                "limit": 1,
            },
        )
        assert first_page.status_code == 200
        first_payload = first_page.json()
        assert first_payload["items"] == [
            {
                "workflow_id": "wf-beta",
                "tenant_id": "tenant-a",
                "name": "Beta Workflow",
                "status": "draft",
                "latest_version": 1,
            }
        ]
        assert first_payload["next_cursor"] is not None

        second_page = await client.get(
            "/v1/workflows",
            params={
                "tenant_id": "tenant-a",
                "workflow_id_prefix": "wf-",
                "name_query": "workflow",
                "limit": 1,
                "cursor": first_payload["next_cursor"],
            },
        )
        assert second_page.status_code == 200
        assert second_page.json()["items"] == [
            {
                "workflow_id": "wf-gamma",
                "tenant_id": "tenant-a",
                "name": "Gamma Workflow",
                "status": "draft",
                "latest_version": 1,
            }
        ]
        assert second_page.json()["next_cursor"] is None

        invalid_cursor_response = await client.get(
            "/v1/workflows",
            params={"tenant_id": "tenant-a", "cursor": "bad-cursor"},
        )
        assert invalid_cursor_response.status_code == 400
```

- [ ] **Step 2: Add workflow list schemas for lightweight items and list response**

```python
class WorkflowListItemResponse(BaseModel):
    workflow_id: str
    tenant_id: str
    name: str
    status: str
    latest_version: int


class WorkflowListResponse(BaseModel):
    items: list[WorkflowListItemResponse] = Field(default_factory=list)
    next_cursor: str | None = None
```

- [ ] **Step 3: Change `GET /v1/workflows` to the new query contract and preserve current exception mapping**

```python
@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    request: Request,
    tenant_id: str,
    workflow_id_prefix: str | None = None,
    name_query: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> WorkflowListResponse:
    try:
        result = await request.app.state.workflow_service.list_workflows(
            tenant_id=tenant_id,
            workflow_id_prefix=workflow_id_prefix,
            name_query=name_query,
            limit=limit,
            cursor=cursor,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)

    return WorkflowListResponse(
        items=[WorkflowListItemResponse.model_validate(item) for item in result["items"]],
        next_cursor=result["next_cursor"],
    )
```

- [ ] **Step 4: Run the focused integration suite to verify the new list contract passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflows_api.py -v`
Expected: PASS with the new lightweight workflow list response while existing detail/lifecycle integration behavior remains green.

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api/schemas.py src/agent_runtime/api/routes/workflows.py tests/integration/test_workflows_api.py
git commit -m "feat: add workflow management query route"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 4: Run Workflow-Focused Verification And Lock In No-Regression Behavior

**Files:**
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`

- [ ] **Step 1: Run the workflow-focused verification suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflows_api.py tests\integration\test_workflow_templates_api.py -v`
Expected: PASS

- [ ] **Step 2: Run the full regression suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS

- [ ] **Step 3: Re-check spec and plan alignment**

Run: `rg -n "workflow_id_prefix|name_query|cursor|created_at desc|workflow_id asc|items \\+ next_cursor|description search|run-history|governance" docs/superpowers/specs/2026-05-18-agent-runtime-workflow-management-query-api-design.md docs/superpowers/plans/2026-05-18-agent-runtime-workflow-management-query-api.md`
Expected: the plan covers the list endpoint, filters, pagination, lightweight response, and deferred follow-up boundaries from the spec.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_workflow_service.py tests/integration/test_workflows_api.py tests/integration/test_workflow_templates_api.py
git commit -m "test: verify workflow management query api"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Self-Review

- Spec coverage:
  - lightweight backend-facing `GET /v1/workflows`: Task 3
  - tenant-scoped list query only: Tasks 2 and 3
  - `workflow_id_prefix` and `name_query` filters: Tasks 1, 2, and 3
  - cursor pagination with `created_at desc, workflow_id asc`: Tasks 1 and 2
  - `items + next_cursor` response only: Task 3
  - no regression to detail/lifecycle/template compatibility behavior: Tasks 3 and 4

- Placeholder scan:
  - all tasks include concrete file paths, code shapes, commands, and expected outcomes
  - commit steps are preserved for workflow parity, but explicitly marked non-executable unless commit is later requested

- Type consistency:
  - internal storage remains `template_id`, outward list responses expose `workflow_id`
  - route method is `list_workflows(...)`, service method is `list_workflows(...)`, repository method is `list_workflow_summaries(...)`
  - list responses consistently use `WorkflowListItemResponse` inside `WorkflowListResponse`
