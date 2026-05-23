# Agent Runtime Workflow V2 Resource Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first `workflow v2` phase by introducing a recommended `/v1/workflows` API family, completing draft/publish/archive lifecycle behavior on top of the existing workflow-template implementation, and preserving compatibility with `/v1/workflow-templates`.

**Architecture:** This phase keeps the current runtime, workflow repository, and launch path as the only execution kernel. The implementation extends the existing workflow-template persistence model with additional lifecycle metadata, moves more lifecycle orchestration into `WorkflowService`, adds a new `/v1/workflows` route family, and keeps old template routes as same-data compatibility adapters rather than creating a second storage model.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite, httpx, pytest, pytest-asyncio

---

## File Structure

### New Files

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflows.py`
  Recommended workflow-v2 route family backed by the same service as workflow-template routes.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
  Integration coverage for `/v1/workflows` lifecycle, same-data compatibility, and workflow-v2 regressions.

### Modified Files

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\domain\models.py`
  Extend workflow header/version records with workflow-v2 lifecycle metadata.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\tables.py`
  Add workflow-v2 lifecycle columns needed by the existing storage model.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\db.py`
  Add upgrade-safe schema patching for new workflow-v2 columns.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
  Add detail queries, draft lookup, copy-latest draft creation, delete, replace, and archive persistence helpers.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\service.py`
  Add workflow-v2 lifecycle orchestration, publish preflight aggregation, and compatibility adapters.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
  Add workflow-v2 request/response schemas while retaining workflow-template compatibility schemas.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_templates.py`
  Keep existing template routes working and optionally expose mirrored lifecycle endpoints through the same service.

- `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
  Wire the new workflow-v2 router.

- `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
  Add unit coverage for workflow-v2 lifecycle and schema upgrades.

- `C:\Users\Ilya\PycharmProjects\AGENT\docs\deferred-roadmap.md`
  Update the active next-phase row so the roadmap reflects workflow v2 as the current implementation target.

### Verification Commands

- Focused unit suite:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
- Focused workflow API suites:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_templates_api.py tests\integration\test_workflows_api.py -v`
- Full regression:
  `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`

### Task 1: Add Workflow V2 Lifecycle Metadata And Red Unit Tests

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\domain\models.py`

- [ ] **Step 1: Write failing unit tests for draft lifecycle, archive metadata, and publish preflight aggregation**

```python
def test_validate_template_definition_rejects_invalid_input_schema_envelope() -> None:
    service = load_workflow_service()
    with pytest.raises(service.WorkflowTemplateValidationError, match="input_schema must declare type=object"):
        service.WorkflowService._validate_workflow_input_schema({"type": "array"})


@pytest.mark.asyncio
async def test_workflow_service_create_draft_version_copies_latest_and_rejects_second_draft(tmp_path) -> None:
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
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incidents",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object", "required": ["ticket_id"]},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        draft = await service.create_template_version_draft(
            tenant_id="tenant-a",
            template_id="wf-triage",
            created_by="operator-b",
        )

        assert draft.version == 2
        assert draft.source_version == 1
        assert draft.definition == {"entrypoint": {"objective_template": "Triage {ticket_id}"}}

        with pytest.raises(workflow_service_module.WorkflowTemplateConflictError, match="draft already exists"):
            await service.create_template_version_draft(
                tenant_id="tenant-a",
                template_id="wf-triage",
                created_by="operator-c",
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_publish_template_version_aggregates_preflight_errors(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        workflow_service_module = load_workflow_service()

        class StubKnowledgeRepository:
            async def list_knowledge_bases(self, tenant_id: str):
                del tenant_id
                return []

        class StubRunService:
            async def create_run_from_template_launch(self, **kwargs):
                raise AssertionError("not used in this test")

        runtime_repository = RuntimeRepository(session_factory)
        await runtime_repository.upsert_tenant_policy(
            TenantPolicyRecord(
                tenant_id="tenant-a",
                allowed_tools=["rag_search"],
                approval_required_tools=[],
            )
        )

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-bad",
                tenant_id="tenant-a",
                name="Broken Workflow",
                description="Broken workflow",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-bad",
                version=1,
                definition={
                    "entrypoint": {"objective_template": ""},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": -1},
                    "tools": {"allowed_tools": ["payment-api"], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": ["kb-missing"], "allow_kb_override": False},
                    "runtime": {"max_turns": -2, "timeout_seconds": 60, "tags": []},
                    "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
                },
                input_schema={"type": "array"},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplatePreflightError) as exc_info:
            await service.publish_template_version(
                tenant_id="tenant-a",
                template_id="wf-bad",
                version=1,
            )

        assert exc_info.value.errors == [
            "entrypoint.objective_template must be a non-empty string",
            "agents.max_worker_count must be non-negative",
            "runtime.max_turns must be non-negative",
            "input_schema must declare type=object",
            "template tools exceed tenant policy: payment-api",
            "unknown knowledge base: kb-missing",
        ]
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 2: Run the focused unit suite to verify the new tests fail for missing workflow-v2 lifecycle behavior**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: FAIL with missing `latest_published_version`, `source_version`, `create_template_version_draft(...)`, or `WorkflowTemplatePreflightError`.

- [ ] **Step 3: Extend workflow domain records with workflow-v2 lifecycle fields**

```python
class WorkflowTemplateRecord(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int = 0
    latest_published_version: int | None = None
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowTemplateVersionRecord(BaseModel):
    template_id: str
    version: int
    definition: dict[str, Any]
    input_schema: dict[str, Any]
    is_published: bool = False
    published_at: datetime | None = None
    source_version: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str | None = None
```

- [ ] **Step 4: Run the focused unit suite again to move the failure point into repository or service logic**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: FAIL in repository persistence or `WorkflowService` lifecycle methods, not in missing model fields.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_workflow_service.py src/agent_runtime/domain/models.py
git commit -m "test: add workflow v2 lifecycle red tests"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 2: Add Repository Persistence, Schema Upgrades, And Lifecycle Helpers

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\tables.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\db.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`

- [ ] **Step 1: Extend the unit suite with repository-level lifecycle and upgrade tests**

```python
@pytest.mark.asyncio
async def test_workflow_repository_delete_draft_version_preserves_published_history(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)

        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incidents",
                status="published",
                latest_version=1,
                latest_published_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                is_published=True,
                created_by="operator-a",
            ),
        )
        await workflow_repository.create_template_version(
            "tenant-a",
            "wf-triage",
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=2,
                definition={"entrypoint": {"objective_template": "Escalate {ticket_id}"}},
                input_schema={"type": "object"},
                source_version=1,
                created_by="operator-b",
            ),
        )

        await workflow_repository.delete_draft_version("tenant-a", "wf-triage", 2)

        stored_version = await workflow_repository.get_template_version("tenant-a", "wf-triage", 2)
        stored_template = await workflow_repository.get_template("tenant-a", "wf-triage")

        assert stored_version is None
        assert stored_template is not None
        assert stored_template.latest_version == 1
        assert stored_template.latest_published_version == 1
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_init_db_upgrades_existing_workflow_tables_with_v2_columns(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            '''
            CREATE TABLE workflow_templates (
                template_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE workflow_template_versions (
                version_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                definition JSON NOT NULL,
                input_schema JSON NOT NULL,
                is_published BOOLEAN NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT
            );
            '''
        )
        connection.commit()
    finally:
        connection.close()

    session_factory = build_session_factory(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(session_factory)
        workflow_repository = load_workflow_repository()(session_factory)
        await workflow_repository.create_template(
            WorkflowTemplateRecord(
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incidents",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                source_version=None,
                created_by="operator-a",
            ),
        )
        stored_template = await workflow_repository.get_template("tenant-a", "wf-triage")
        stored_version = await workflow_repository.get_template_version("tenant-a", "wf-triage", 1)
        assert stored_template is not None
        assert stored_template.latest_published_version is None
        assert stored_template.archived_at is None
        assert stored_version is not None
        assert stored_version.source_version is None
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 2: Run the focused unit suite to verify repository and schema-upgrade tests fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: FAIL with missing table columns, missing repository methods, or missing schema upgrade logic.

- [ ] **Step 3: Add workflow-v2 columns to tables**

```python
class WorkflowTemplateTable(Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_id", name="uq_workflow_templates_tenant_template"),
    )

    template_pk: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    latest_version: Mapped[int]
    latest_published_version: Mapped[int | None]
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class WorkflowTemplateVersionTable(Base):
    __tablename__ = "workflow_template_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["workflow_templates.tenant_id", "workflow_templates.template_id"],
            name="fk_workflow_template_versions_template",
        ),
        UniqueConstraint("tenant_id", "template_id", "version", name="uq_workflow_template_versions"),
    )

    version_pk: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int]
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_published: Mapped[bool] = mapped_column(index=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    source_version: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

- [ ] **Step 4: Add schema-upgrade-safe initialization for the new workflow-v2 columns**

```python
async def _upgrade_workflow_v2_columns(connection) -> None:
    template_columns = {row[1] for row in await connection.execute(text("PRAGMA table_info(workflow_templates)"))}
    if "latest_published_version" not in template_columns:
        await connection.execute(
            text("ALTER TABLE workflow_templates ADD COLUMN latest_published_version INTEGER")
        )
    if "archived_at" not in template_columns:
        await connection.execute(
            text("ALTER TABLE workflow_templates ADD COLUMN archived_at DATETIME")
        )

    version_columns = {
        row[1] for row in await connection.execute(text("PRAGMA table_info(workflow_template_versions)"))
    }
    if "source_version" not in version_columns:
        await connection.execute(
            text("ALTER TABLE workflow_template_versions ADD COLUMN source_version INTEGER")
        )
```

- [ ] **Step 5: Add repository helpers for detail, draft lookup, copy-from-latest, replace, delete, and archive**

```python
async def get_draft_version(self, tenant_id: str, template_id: str) -> WorkflowTemplateVersionRecord | None:
    async with self._session_factory() as session:
        row = (
            await session.execute(
                select(WorkflowTemplateVersionTable)
                .where(
                    WorkflowTemplateVersionTable.tenant_id == tenant_id,
                    WorkflowTemplateVersionTable.template_id == template_id,
                    WorkflowTemplateVersionTable.is_published.is_(False),
                )
                .order_by(WorkflowTemplateVersionTable.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return None if row is None else self._map_version(row)


async def create_copied_draft_version(
    self,
    tenant_id: str,
    template_id: str,
    *,
    created_by: str | None,
) -> WorkflowTemplateVersionRecord:
    async with self._session_factory() as session:
        async with session.begin():
            template_row = (
                await session.execute(
                    select(WorkflowTemplateTable).where(
                        WorkflowTemplateTable.tenant_id == tenant_id,
                        WorkflowTemplateTable.template_id == template_id,
                    )
                )
            ).scalar_one()
            existing_draft = (
                await session.execute(
                    select(WorkflowTemplateVersionTable).where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.is_published.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if existing_draft is not None:
                raise RuntimeError("draft already exists")

            source_row = (
                await session.execute(
                    select(WorkflowTemplateVersionTable)
                    .where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                    )
                    .order_by(WorkflowTemplateVersionTable.version.desc())
                    .limit(1)
                )
            ).scalar_one()
            next_version = template_row.latest_version + 1
            created_at = utc_now()
            draft_row = WorkflowTemplateVersionTable(
                tenant_id=tenant_id,
                template_id=template_id,
                version=next_version,
                definition=source_row.definition,
                input_schema=source_row.input_schema,
                is_published=False,
                published_at=None,
                source_version=source_row.version,
                created_at=created_at,
                created_by=created_by,
            )
            template_row.latest_version = next_version
            template_row.updated_at = created_at
            session.add(draft_row)
        return WorkflowTemplateVersionRecord(
            template_id=template_id,
            version=next_version,
            definition=source_row.definition,
            input_schema=source_row.input_schema,
            is_published=False,
            published_at=None,
            source_version=source_row.version,
            created_at=created_at,
            created_by=created_by,
        )
```

- [ ] **Step 6: Run the focused unit suite to verify repository and upgrade behavior passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: PASS for repository lifecycle and schema upgrade coverage, with remaining failures only in service or API behavior not yet implemented.

- [ ] **Step 7: Commit**

```bash
git add src/agent_runtime/state/tables.py src/agent_runtime/state/db.py src/agent_runtime/workflows/repository.py tests/unit/test_workflow_service.py
git commit -m "feat: add workflow v2 persistence lifecycle"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 3: Implement Workflow V2 Service Lifecycle And Publish Preflight

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\service.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`

- [ ] **Step 1: Add failing unit tests for detail retrieval, draft replace/delete, and archive rules**

```python
@pytest.mark.asyncio
async def test_workflow_service_get_template_detail_returns_latest_draft_and_latest_published(tmp_path) -> None:
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
                template_id="wf-triage",
                tenant_id="tenant-a",
                name="Incident Triage",
                description="Triage incidents",
                status="published",
                latest_version=2,
                latest_published_version=1,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=1,
                definition={"entrypoint": {"objective_template": "Triage {ticket_id}"}},
                input_schema={"type": "object"},
                is_published=True,
                created_by="operator-a",
            ),
        )
        await workflow_repository.create_template_version(
            "tenant-a",
            "wf-triage",
            WorkflowTemplateVersionRecord(
                template_id="wf-triage",
                version=2,
                definition={"entrypoint": {"objective_template": "Escalate {ticket_id}"}},
                input_schema={"type": "object"},
                source_version=1,
                created_by="operator-b",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        detail = await service.get_template_detail("tenant-a", "wf-triage")

        assert detail["template"].latest_version == 2
        assert detail["template"].latest_published_version == 1
        assert detail["latest_draft"].version == 2
        assert detail["latest_published"].version == 1
        assert [item["version"] for item in detail["version_summaries"]] == [2, 1]
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_workflow_service_archive_template_rejects_unpublished_only_workflow(tmp_path) -> None:
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
                template_id="wf-draft",
                tenant_id="tenant-a",
                name="Draft Workflow",
                description="Draft only",
                status="draft",
                latest_version=1,
                latest_published_version=None,
            ),
            WorkflowTemplateVersionRecord(
                template_id="wf-draft",
                version=1,
                definition={"entrypoint": {"objective_template": "Draft {ticket_id}"}},
                input_schema={"type": "object"},
                created_by="operator-a",
            ),
        )

        service = workflow_service_module.WorkflowService(
            workflow_repository=workflow_repository,
            runtime_repository=runtime_repository,
            knowledge_repository=StubKnowledgeRepository(),
            run_service=StubRunService(),
        )

        with pytest.raises(workflow_service_module.WorkflowTemplateValidationError, match="cannot archive unpublished workflow"):
            await service.archive_template("tenant-a", "wf-draft")
    finally:
        await dispose_session_factory(session_factory)
```

- [ ] **Step 2: Run the focused unit suite to verify service-lifecycle tests fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: FAIL with missing `get_template_detail(...)`, `replace_template_version_draft(...)`, `delete_template_version(...)`, `archive_template(...)`, or preflight aggregation behavior.

- [ ] **Step 3: Add explicit workflow-v2 service exceptions and input-schema validation helper**

```python
class WorkflowTemplatePreflightError(WorkflowTemplateValidationError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class WorkflowService:
    @staticmethod
    def _validate_workflow_input_schema(input_schema: dict[str, Any]) -> None:
        if not input_schema:
            return
        if input_schema.get("type") != "object":
            raise WorkflowTemplateValidationError("input_schema must declare type=object")
        required_fields = input_schema.get("required", [])
        if not isinstance(required_fields, list):
            raise WorkflowTemplateValidationError("input_schema required must be a list")
```

- [ ] **Step 4: Implement detail, draft copy, replace, delete, archive, and preflight aggregation in `WorkflowService`**

```python
async def get_template_detail(self, tenant_id: str, template_id: str) -> dict[str, Any]:
    template = await self._repository.get_template(tenant_id, template_id)
    if template is None:
        raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
    latest_draft = await self._repository.get_draft_version(tenant_id, template_id)
    latest_published = await self._repository.get_latest_published_version(tenant_id, template_id)
    version_summaries = await self._repository.list_template_versions(tenant_id, template_id)
    return {
        "template": template,
        "latest_draft": latest_draft,
        "latest_published": latest_published,
        "version_summaries": version_summaries,
    }


async def create_template_version_draft(
    self,
    *,
    tenant_id: str,
    template_id: str,
    created_by: str | None,
) -> WorkflowTemplateVersionRecord:
    template = await self._repository.get_template(tenant_id, template_id)
    if template is None:
        raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
    try:
        return await self._repository.create_copied_draft_version(
            tenant_id,
            template_id,
            created_by=created_by,
        )
    except RuntimeError as exc:
        raise WorkflowTemplateConflictError(str(exc)) from exc


async def replace_template_version_draft(
    self,
    *,
    tenant_id: str,
    template_id: str,
    version: int,
    definition: dict[str, Any],
    input_schema: dict[str, Any],
) -> WorkflowTemplateVersionRecord:
    errors = validate_template_definition(definition)
    if errors:
        raise WorkflowTemplateValidationError("; ".join(errors))
    self._validate_workflow_input_schema(input_schema)
    return await self._repository.replace_draft_version(
        tenant_id=tenant_id,
        template_id=template_id,
        version=version,
        definition=definition,
        input_schema=input_schema,
    )


async def delete_template_version(
    self,
    *,
    tenant_id: str,
    template_id: str,
    version: int,
) -> None:
    version_record = await self._repository.get_template_version(tenant_id, template_id, version)
    if version_record is None:
        raise WorkflowTemplateNotFoundError(f"workflow template version not found: {template_id}:{version}")
    if version_record.is_published:
        raise WorkflowTemplateValidationError(f"cannot delete published workflow template version: {template_id}:{version}")
    await self._repository.delete_draft_version(tenant_id, template_id, version)


async def archive_template(self, tenant_id: str, template_id: str) -> WorkflowTemplateRecord:
    template = await self._repository.get_template(tenant_id, template_id)
    if template is None:
        raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
    if template.latest_published_version is None:
        raise WorkflowTemplateValidationError(f"cannot archive unpublished workflow template: {template_id}")
    await self._repository.archive_template(tenant_id, template_id)
    archived = await self._repository.get_template(tenant_id, template_id)
    if archived is None:
        raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
    return archived
```

- [ ] **Step 5: Change publish flow to run a full preflight check and return aggregated errors**

```python
async def publish_template_version(
    self,
    *,
    tenant_id: str,
    template_id: str,
    version: int,
) -> WorkflowTemplateRecord:
    template = await self._repository.get_template(tenant_id, template_id)
    if template is None:
        raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")

    version_record = await self._repository.get_template_version(tenant_id, template_id, version)
    if version_record is None:
        raise WorkflowTemplateNotFoundError(f"workflow template version not found: {template_id}:{version}")
    if version_record.is_published:
        raise WorkflowTemplateValidationError(f"workflow template version is already published: {template_id}:{version}")

    errors = validate_template_definition(version_record.definition)
    try:
        self._validate_workflow_input_schema(version_record.input_schema)
    except WorkflowTemplateValidationError as exc:
        errors.append(str(exc))

    tenant_policy = await self._runtime_repository.get_tenant_policy(tenant_id)
    if tenant_policy is None:
        errors.append(f"tenant policy not found: {tenant_id}")
    else:
        template_tools = version_record.definition.get("tools", {}).get("allowed_tools", [])
        disallowed_tools = sorted(set(template_tools).difference(tenant_policy.allowed_tools))
        if disallowed_tools:
            errors.append(f"template tools exceed tenant policy: {', '.join(disallowed_tools)}")

    knowledge_bases = await self._knowledge_repository.list_knowledge_bases(tenant_id)
    existing_kb_ids = {item.kb_id for item in knowledge_bases}
    for kb_id in version_record.definition.get("knowledge", {}).get("default_kb_ids", []):
        if kb_id not in existing_kb_ids:
            errors.append(f"unknown knowledge base: {kb_id}")

    if errors:
        raise WorkflowTemplatePreflightError(errors)

    await self._repository.publish_version(tenant_id, template_id, version)
    published_template = await self._repository.get_template(tenant_id, template_id)
    if published_template is None:
        raise WorkflowTemplateNotFoundError(f"workflow template not found: {template_id}")
    return published_template
```

- [ ] **Step 6: Run the focused unit suite to verify workflow-v2 service behavior passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/agent_runtime/workflows/service.py tests/unit/test_workflow_service.py
git commit -m "feat: add workflow v2 service lifecycle"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 4: Add `/v1/workflows` Routes, Compatibility Adapters, And Integration Coverage

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflows.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_templates.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`

- [ ] **Step 1: Write failing integration tests for `/v1/workflows` lifecycle and same-data compatibility**

```python
@pytest.mark.asyncio
async def test_workflow_v2_create_detail_copy_publish_archive_and_launch(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": [ModelDecision(kind="finish", summary="done", final_output="triaged")]}),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        await client.put(
            "/v1/tenants/tenant-a/policies",
            json={"allowed_tools": [], "approval_required_tools": []},
        )

        create_response = await client.post(
            "/v1/workflows",
            json={
                "workflow_id": "wf-triage",
                "tenant_id": "tenant-a",
                "name": "Incident Triage",
                "description": "Triage incidents",
                "definition": {
                    "entrypoint": {"objective_template": "Triage {ticket_id}", "result_contract": "string"},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                    "tools": {"allowed_tools": [], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                    "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": ["ops"]},
                    "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
                },
                "input_schema": {"type": "object", "required": ["ticket_id"]},
                "created_by": "operator-a",
            },
        )
        assert create_response.status_code == 201

        detail_response = await client.get("/v1/workflows/wf-triage", params={"tenant_id": "tenant-a"})
        assert detail_response.status_code == 200
        assert detail_response.json()["workflow_id"] == "wf-triage"
        assert detail_response.json()["latest_draft"]["version"] == 1

        create_version_response = await client.post(
            "/v1/workflows/wf-triage/versions",
            json={"tenant_id": "tenant-a", "created_by": "operator-b"},
        )
        assert create_version_response.status_code == 409

        publish_response = await client.post(
            "/v1/workflows/wf-triage/versions/1/publish",
            json={"tenant_id": "tenant-a"},
        )
        assert publish_response.status_code == 200

        copied_version_response = await client.post(
            "/v1/workflows/wf-triage/versions",
            json={"tenant_id": "tenant-a", "created_by": "operator-b"},
        )
        assert copied_version_response.status_code == 201
        assert copied_version_response.json()["source_version"] == 1

        replace_response = await client.put(
            "/v1/workflows/wf-triage/versions/2",
            json={
                "tenant_id": "tenant-a",
                "definition": {
                    "entrypoint": {"objective_template": "Escalate {ticket_id}", "result_contract": "string"},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                    "tools": {"allowed_tools": [], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                    "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": ["ops"]},
                    "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
                },
                "input_schema": {"type": "object", "required": ["ticket_id"]},
            },
        )
        assert replace_response.status_code == 200

        delete_response = await client.delete(
            "/v1/workflows/wf-triage/versions/2",
            params={"tenant_id": "tenant-a"},
        )
        assert delete_response.status_code == 204

        archive_response = await client.post(
            "/v1/workflows/wf-triage/archive",
            json={"tenant_id": "tenant-a"},
        )
        assert archive_response.status_code == 200


@pytest.mark.asyncio
async def test_workflow_v2_and_workflow_template_routes_share_same_resource_state(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )
    async with app_client_context(app) as client:
        await client.post(
            "/v1/workflows",
            json={
                "workflow_id": "wf-shared",
                "tenant_id": "tenant-a",
                "name": "Shared Workflow",
                "description": "Shared data",
                "definition": {
                    "entrypoint": {"objective_template": "Triage {ticket_id}", "result_contract": "string"},
                    "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                    "tools": {"allowed_tools": [], "approval_required_tools": []},
                    "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                    "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": ["ops"]},
                    "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
                },
                "input_schema": {"type": "object", "required": ["ticket_id"]},
            },
        )

        template_list_response = await client.get("/v1/workflow-templates", params={"tenant_id": "tenant-a"})
        workflow_detail_response = await client.get("/v1/workflows/wf-shared", params={"tenant_id": "tenant-a"})

        assert template_list_response.status_code == 200
        assert template_list_response.json()[0]["template_id"] == "wf-shared"
        assert workflow_detail_response.status_code == 200
        assert workflow_detail_response.json()["workflow_id"] == "wf-shared"
```

- [ ] **Step 2: Run the workflow-focused integration suites to verify the new route tests fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_templates_api.py tests\integration\test_workflows_api.py -v`
Expected: FAIL with missing `/v1/workflows` routes, missing schemas, or missing compatibility lifecycle endpoints.

- [ ] **Step 3: Add workflow-v2 request and response schemas**

```python
class WorkflowCreateRequest(BaseModel):
    workflow_id: str
    tenant_id: str
    name: str
    description: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class WorkflowVersionCreateRequest(BaseModel):
    tenant_id: str
    created_by: str | None = None


class WorkflowVersionReplaceRequest(BaseModel):
    tenant_id: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)


class WorkflowArchiveRequest(BaseModel):
    tenant_id: str


class WorkflowVersionSummaryResponse(BaseModel):
    version: int
    status: str
    is_published: bool
    source_version: int | None
    created_by: str | None


class WorkflowDetailResponse(BaseModel):
    workflow_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int
    latest_published_version: int | None
    archived_at: datetime | None
    latest_draft: dict[str, Any] | None
    latest_published: dict[str, Any] | None
    version_summaries: list[WorkflowVersionSummaryResponse]
```

- [ ] **Step 4: Add the new `/v1/workflows` router and map workflow-v2 exceptions to stable HTTP responses**

```python
router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(request: Request, payload: WorkflowCreateRequest) -> WorkflowResponse:
    workflow = await request.app.state.workflow_service.create_template(
        template_id=payload.workflow_id,
        tenant_id=payload.tenant_id,
        name=payload.name,
        description=payload.description,
        definition=payload.definition,
        input_schema=payload.input_schema,
        created_by=payload.created_by,
    )
    return WorkflowResponse(
        workflow_id=workflow.template_id,
        tenant_id=workflow.tenant_id,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        latest_version=workflow.latest_version,
        latest_published_version=workflow.latest_published_version,
        archived_at=workflow.archived_at,
    )


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow_detail(request: Request, workflow_id: str, tenant_id: str) -> WorkflowDetailResponse:
    detail = await request.app.state.workflow_service.get_template_detail(tenant_id, workflow_id)
    return WorkflowDetailResponse(
        workflow_id=detail["template"].template_id,
        tenant_id=detail["template"].tenant_id,
        name=detail["template"].name,
        description=detail["template"].description,
        status=detail["template"].status,
        latest_version=detail["template"].latest_version,
        latest_published_version=detail["template"].latest_published_version,
        archived_at=detail["template"].archived_at,
        latest_draft=_serialize_version(detail["latest_draft"]),
        latest_published=_serialize_version(detail["latest_published"]),
        version_summaries=[WorkflowVersionSummaryResponse(**item) for item in detail["version_summaries"]],
    )
```

- [ ] **Step 5: Mirror new lifecycle behavior into compatibility routes where the old family needs equivalent capabilities**

```python
@router.get("/{template_id}", response_model=WorkflowTemplateDetailResponse)
async def get_workflow_template_detail(request: Request, template_id: str, tenant_id: str) -> WorkflowTemplateDetailResponse:
    detail = await request.app.state.workflow_service.get_template_detail(tenant_id, template_id)
    return WorkflowTemplateDetailResponse(
        template_id=detail["template"].template_id,
        tenant_id=detail["template"].tenant_id,
        name=detail["template"].name,
        description=detail["template"].description,
        status=detail["template"].status,
        latest_version=detail["template"].latest_version,
        latest_published_version=detail["template"].latest_published_version,
        archived_at=detail["template"].archived_at,
        latest_draft=_serialize_template_version(detail["latest_draft"]),
        latest_published=_serialize_template_version(detail["latest_published"]),
        version_summaries=[WorkflowTemplateVersionSummaryResponse(**item) for item in detail["version_summaries"]],
    )


@router.post("/{template_id}/versions", response_model=WorkflowTemplateVersionResponse, status_code=201)
async def create_workflow_template_version(request: Request, template_id: str, payload: WorkflowTemplateVersionCreateRequest) -> WorkflowTemplateVersionResponse:
    version = await request.app.state.workflow_service.create_template_version_draft(
        tenant_id=payload.tenant_id,
        template_id=template_id,
        created_by=payload.created_by,
    )
    return WorkflowTemplateVersionResponse.model_validate(version.model_dump())
```

- [ ] **Step 6: Wire the new router into the application**

```python
from agent_runtime.api.routes.workflows import router as workflows_router


def create_app(...) -> FastAPI:
    ...
    app.include_router(workflows_router)
    app.include_router(workflow_templates_router)
    return app
```

- [ ] **Step 7: Run the workflow-focused integration suites to verify workflow-v2 API and compatibility behavior passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\integration\test_workflow_templates_api.py tests\integration\test_workflows_api.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/agent_runtime/api/routes/workflows.py src/agent_runtime/api/routes/workflow_templates.py src/agent_runtime/api/schemas.py src/agent_runtime/api/app.py tests/integration/test_workflows_api.py tests/integration/test_workflow_templates_api.py
git commit -m "feat: add workflow v2 api lifecycle"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 5: Align Roadmap And Run Final Verification

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\deferred-roadmap.md`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflows_api.py`

- [ ] **Step 1: Update the roadmap so workflow v2 is the active phase**

```markdown
## Active Next Phase

| Item | Status | Target Phase | Notes |
| --- | --- | --- | --- |
| Workflow v2 resource lifecycle | selected for immediate implementation | next phase | add `/v1/workflows`, detail views, draft lifecycle, publish preflight, and compatibility routing on top of workflow templates |
```

- [ ] **Step 2: Run the focused workflow-v2 suites**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests\unit\test_workflow_service.py tests\integration\test_workflow_templates_api.py tests\integration\test_workflows_api.py -v`
Expected: PASS

- [ ] **Step 3: Run the full regression suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS

- [ ] **Step 4: Re-check spec and roadmap alignment**

Run: `rg -n "workflow v2|/v1/workflows|workflow-templates|visual workflow|one-shot|tracing|external vector|semantic chunk" docs/superpowers/specs/2026-05-18-agent-runtime-workflow-v2-resource-lifecycle-design.md docs/deferred-roadmap.md`
Expected: workflow-v2 scope is present, visual builder and one-shot execution remain deferred, and the roadmap reflects the new active phase.

- [ ] **Step 5: Commit**

```bash
git add docs/deferred-roadmap.md tests/unit/test_workflow_service.py tests/integration/test_workflow_templates_api.py tests/integration/test_workflows_api.py
git commit -m "test: verify workflow v2 lifecycle end to end"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Self-Review

- Spec coverage:
  - `/v1/workflows` recommended API surface: Task 4
  - same-data compatibility with `/v1/workflow-templates`: Task 4
  - draft copy / single draft / replace / delete / archive lifecycle: Tasks 2, 3, and 4
  - publish preflight aggregation: Task 3
  - workflow-v2 regression protection for approval and RAG: Task 4 and Task 5
  - roadmap alignment for the new active phase: Task 5

- Placeholder scan:
  - all tasks include concrete file paths, code shapes, commands, and expected outcomes
  - commit steps are preserved for workflow parity, but marked as non-executable unless commit is later requested

- Type consistency:
  - internal storage remains `template_id`, external workflow-v2 routes use `workflow_id`
  - new lifecycle methods consistently use `create_template_version_draft`, `replace_template_version_draft`, `delete_template_version`, `archive_template`, and `get_template_detail`
  - publish-time aggregated failures consistently use `WorkflowTemplatePreflightError`
