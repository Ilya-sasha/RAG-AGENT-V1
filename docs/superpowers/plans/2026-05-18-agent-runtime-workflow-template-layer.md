# Agent Runtime Workflow Template Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-generation declarative workflow template layer that stores reusable workflow assets, publishes immutable versions, and launches normal runtime runs from a published template.

**Architecture:** The implementation adds a narrow `workflows` package that validates and assembles published templates into existing runtime run launches. Execution stays inside the current `RunService`, `RuntimeOrchestrator`, `ToolGateway`, approval flow, and RAG path; the new layer only persists workflow assets, validates launch input, computes effective policy metadata, and links runs back to template versions for audit.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, aiosqlite, httpx, pytest, pytest-asyncio

---

## File Structure

### New Files

- `src/agent_runtime/workflows/__init__.py`
  Package marker and public exports for workflow template types and services.

- `src/agent_runtime/workflows/assembler.py`
  Objective rendering, effective-policy composition, and template launch assembly helpers.

- `src/agent_runtime/workflows/repository.py`
  Durable workflow template CRUD, version storage, publish, and run-link persistence.

- `src/agent_runtime/workflows/service.py`
  High-level template validation, lifecycle rules, and template launch orchestration.

- `src/agent_runtime/api/routes/workflow_templates.py`
  Internal API for template create/list/detail/version/publish/launch.

- `tests/unit/test_workflow_service.py`
  Unit coverage for definition validation, objective assembly, policy composition, and publish rules.

- `tests/integration/test_workflow_templates_api.py`
  Integration coverage for template lifecycle, launch, tenant guardrails, approval behavior, and KB binding checks.

### Modified Files

- `src/agent_runtime/domain/models.py`
  Add domain records for workflow templates, template versions, and run-template linkage.

- `src/agent_runtime/state/tables.py`
  Add SQLAlchemy tables for workflow templates, versions, and run links.

- `src/agent_runtime/state/repositories.py`
  Keep runtime repository focused, but add minimal run-link read support only if needed by existing run queries.

- `src/agent_runtime/api/schemas.py`
  Add workflow template request/response schemas and launch response metadata shape.

- `src/agent_runtime/runtime/services.py`
  Add a template-aware run creation entrypoint that still produces a normal run.

- `src/agent_runtime/api/app.py`
  Wire workflow services and include the workflow template router.

---

### Task 1: Add Workflow Domain Models, Schemas, And Failing Tests

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\domain\models.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`

- [ ] **Step 1: Write the failing unit tests for workflow definition validation and launch assembly**

```python
from agent_runtime.workflows.assembler import assemble_template_launch
from agent_runtime.workflows.service import validate_template_definition


def test_validate_template_definition_rejects_unknown_worker_role() -> None:
    definition = {
        "entrypoint": {"objective_template": "Process {ticket_id}", "result_contract": "string"},
        "agents": {"allowed_worker_roles": ["researcher", "manager"], "max_worker_count": 2},
        "tools": {"allowed_tools": ["rag_search"], "approval_required_tools": []},
        "knowledge": {"default_kb_ids": ["kb-a"], "allow_kb_override": False},
        "runtime": {"max_turns": 6, "timeout_seconds": 300, "tags": ["triage"]},
        "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
    }

    errors = validate_template_definition(definition)

    assert errors == ["unsupported worker role: manager"]


def test_assemble_template_launch_renders_objective_and_effective_policy() -> None:
    assembled = assemble_template_launch(
        tenant_id="tenant-a",
        template_id="wf-triage",
        template_name="Incident Triage",
        version=2,
        definition={
            "entrypoint": {"objective_template": "Triage incident {ticket_id}", "result_contract": "string"},
            "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
            "tools": {"allowed_tools": ["rag_search", "payment-api"], "approval_required_tools": ["payment-api"]},
            "knowledge": {"default_kb_ids": ["kb-ops"], "allow_kb_override": False},
            "runtime": {"max_turns": 8, "timeout_seconds": 600, "tags": ["ops"]},
            "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
        },
        launch_input={"ticket_id": "INC-42"},
        tenant_allowed_tools=["rag_search", "payment-api", "email-api"],
        tenant_approval_required_tools=["email-api"],
        existing_kb_ids=["kb-ops"],
    )

    assert assembled.objective == "Triage incident INC-42"
    assert assembled.default_kb_ids == ["kb-ops"]
    assert assembled.effective_allowed_tools == ["payment-api", "rag_search"]
    assert assembled.effective_approval_required_tools == ["email-api", "payment-api"]
```

- [ ] **Step 2: Run the new unit tests to verify they fail**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py -v`
Expected: FAIL with import errors for `agent_runtime.workflows` symbols or missing workflow models.

- [ ] **Step 3: Add workflow domain records and API schema types**

```python
class WorkflowTemplateRecord(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowTemplateVersionRecord(BaseModel):
    template_id: str
    version: int
    definition: dict[str, Any]
    input_schema: dict[str, Any]
    is_published: bool = False
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str | None = None


class WorkflowRunLinkRecord(BaseModel):
    run_id: str
    tenant_id: str
    template_id: str
    template_version: int
    template_name: str
    launch_input: dict[str, Any]
    effective_workflow_policy: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)
```

```python
class WorkflowTemplateCreateRequest(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    definition: dict[str, Any]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class WorkflowTemplateLaunchRequest(BaseModel):
    tenant_id: str
    version: int | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTemplateResponse(BaseModel):
    template_id: str
    tenant_id: str
    name: str
    description: str
    status: str
    latest_version: int


class WorkflowTemplateLaunchResponse(RunResponse):
    workflow_template: dict[str, Any]
```

- [ ] **Step 4: Run the unit tests again to verify the next failure is in missing service logic**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py -v`
Expected: FAIL in `validate_template_definition(...)` or `assemble_template_launch(...)` not yet existing.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_workflow_service.py src/agent_runtime/domain/models.py src/agent_runtime/api/schemas.py
git commit -m "feat: add workflow template domain records"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 2: Add Workflow Storage Tables And Repository Support

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\__init__.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\repository.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\state\tables.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`

- [ ] **Step 1: Extend the unit tests to cover repository round-trip and publish immutability**

```python
@pytest.mark.asyncio
async def test_workflow_repository_round_trips_template_version_and_run_link(tmp_path) -> None:
    session_factory = build_session_factory(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
    await init_db(session_factory)
    repository = WorkflowRepository(session_factory)

    await repository.create_template(
        WorkflowTemplateRecord(
            template_id="wf-triage",
            tenant_id="tenant-a",
            name="Incident Triage",
            description="Routes incident triage",
            status="draft",
            latest_version=1,
        ),
        WorkflowTemplateVersionRecord(
            template_id="wf-triage",
            version=1,
            definition={"entrypoint": {"objective_template": "Triage {ticket_id}", "result_contract": "string"}},
            input_schema={"type": "object"},
        ),
    )

    await repository.publish_version("tenant-a", "wf-triage", 1)
    await repository.create_run_link(
        WorkflowRunLinkRecord(
            run_id="run-1",
            tenant_id="tenant-a",
            template_id="wf-triage",
            template_version=1,
            template_name="Incident Triage",
            launch_input={"ticket_id": "INC-42"},
            effective_workflow_policy={"allowed_tools": ["rag_search"]},
        )
    )

    template = await repository.get_template("tenant-a", "wf-triage")
    version = await repository.get_template_version("tenant-a", "wf-triage", 1)
    run_link = await repository.get_run_link("run-1")

    assert template is not None and template.status == "published"
    assert version is not None and version.is_published is True
    assert run_link is not None and run_link.template_version == 1
```

- [ ] **Step 2: Run the unit tests to verify repository symbols and tables are still missing**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py -v`
Expected: FAIL with missing `WorkflowRepository` or missing workflow tables.

- [ ] **Step 3: Add workflow tables and repository implementation**

```python
class WorkflowTemplateTable(Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "template_id", name="uq_workflow_templates_tenant_template"),)

    template_pk: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    latest_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime())


class WorkflowTemplateVersionTable(Base):
    __tablename__ = "workflow_template_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "template_id", "version", name="uq_workflow_template_versions"),)

    version_pk: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int]
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_published: Mapped[bool] = mapped_column(index=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorkflowRunLinkTable(Base):
    __tablename__ = "workflow_run_links"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    template_version: Mapped[int]
    template_name: Mapped[str] = mapped_column(String(256))
    launch_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    effective_workflow_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)
```

```python
class WorkflowRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_template(
        self,
        template: WorkflowTemplateRecord,
        version: WorkflowTemplateVersionRecord,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    WorkflowTemplateTable(
                        template_id=template.template_id,
                        tenant_id=template.tenant_id,
                        name=template.name,
                        description=template.description,
                        status=template.status,
                        latest_version=template.latest_version,
                        created_at=template.created_at,
                        updated_at=template.updated_at,
                    )
                )
                session.add(
                    WorkflowTemplateVersionTable(
                        tenant_id=template.tenant_id,
                        template_id=version.template_id,
                        version=version.version,
                        definition=version.definition,
                        input_schema=version.input_schema,
                        is_published=version.is_published,
                        published_at=version.published_at,
                        created_at=version.created_at,
                        created_by=version.created_by,
                    )
                )

    async def create_template_version(self, tenant_id: str, template_id: str, version: WorkflowTemplateVersionRecord) -> None:
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
                template_row.latest_version = version.version
                template_row.updated_at = utc_now()
                session.add(
                    WorkflowTemplateVersionTable(
                        tenant_id=tenant_id,
                        template_id=template_id,
                        version=version.version,
                        definition=version.definition,
                        input_schema=version.input_schema,
                        is_published=version.is_published,
                        published_at=version.published_at,
                        created_at=version.created_at,
                        created_by=version.created_by,
                    )
                )

    async def publish_version(self, tenant_id: str, template_id: str, version: int) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                version_row = (
                    await session.execute(
                        select(WorkflowTemplateVersionTable).where(
                            WorkflowTemplateVersionTable.tenant_id == tenant_id,
                            WorkflowTemplateVersionTable.template_id == template_id,
                            WorkflowTemplateVersionTable.version == version,
                        )
                    )
                ).scalar_one()
                version_row.is_published = True
                version_row.published_at = utc_now()
                template_row = (
                    await session.execute(
                        select(WorkflowTemplateTable).where(
                            WorkflowTemplateTable.tenant_id == tenant_id,
                            WorkflowTemplateTable.template_id == template_id,
                        )
                    )
                ).scalar_one()
                template_row.status = "published"
                template_row.latest_version = version
                template_row.updated_at = utc_now()

    async def get_template(self, tenant_id: str, template_id: str) -> WorkflowTemplateRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateTable).where(
                        WorkflowTemplateTable.tenant_id == tenant_id,
                        WorkflowTemplateTable.template_id == template_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return WorkflowTemplateRecord(
                template_id=row.template_id,
                tenant_id=row.tenant_id,
                name=row.name,
                description=row.description,
                status=row.status,
                latest_version=row.latest_version,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    async def get_template_version(
        self, tenant_id: str, template_id: str, version: int
    ) -> WorkflowTemplateVersionRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateVersionTable).where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.version == version,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return WorkflowTemplateVersionRecord(
                template_id=row.template_id,
                version=row.version,
                definition=row.definition,
                input_schema=row.input_schema,
                is_published=row.is_published,
                published_at=row.published_at,
                created_at=row.created_at,
                created_by=row.created_by,
            )

    async def get_latest_published_version(self, tenant_id: str, template_id: str) -> WorkflowTemplateVersionRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateVersionTable)
                    .where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.is_published.is_(True),
                    )
                    .order_by(WorkflowTemplateVersionTable.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return WorkflowTemplateVersionRecord(
                template_id=row.template_id,
                version=row.version,
                definition=row.definition,
                input_schema=row.input_schema,
                is_published=row.is_published,
                published_at=row.published_at,
                created_at=row.created_at,
                created_by=row.created_by,
            )

    async def list_templates(self, tenant_id: str) -> list[WorkflowTemplateRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(WorkflowTemplateTable)
                    .where(WorkflowTemplateTable.tenant_id == tenant_id)
                    .order_by(WorkflowTemplateTable.created_at, WorkflowTemplateTable.template_id)
                )
            ).scalars()
            return [
                WorkflowTemplateRecord(
                    template_id=row.template_id,
                    tenant_id=row.tenant_id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                    latest_version=row.latest_version,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def create_run_link(self, link: WorkflowRunLinkRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                WorkflowRunLinkTable(
                    run_id=link.run_id,
                    tenant_id=link.tenant_id,
                    template_id=link.template_id,
                    template_version=link.template_version,
                    template_name=link.template_name,
                    launch_input=link.launch_input,
                    effective_workflow_policy=link.effective_workflow_policy,
                    created_at=link.created_at,
                )
            )
            await session.commit()

    async def get_run_link(self, run_id: str) -> WorkflowRunLinkRecord | None:
        async with self._session_factory() as session:
            row = await session.get(WorkflowRunLinkTable, run_id)
            if row is None:
                return None
            return WorkflowRunLinkRecord(
                run_id=row.run_id,
                tenant_id=row.tenant_id,
                template_id=row.template_id,
                template_version=row.template_version,
                template_name=row.template_name,
                launch_input=row.launch_input,
                effective_workflow_policy=row.effective_workflow_policy,
                created_at=row.created_at,
            )
```

- [ ] **Step 4: Run the unit tests to verify repository behavior passes**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py -v`
Expected: PASS for repository round-trip and publish immutability coverage that does not yet depend on service wiring.

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/workflows/__init__.py src/agent_runtime/workflows/repository.py src/agent_runtime/state/tables.py tests/unit/test_workflow_service.py
git commit -m "feat: add workflow template persistence"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 3: Implement Template Validation, Launch Assembly, And Runtime Integration

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\assembler.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\workflows\service.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\runtime\services.py`
- Test: `C:\Users\Ilya\PycharmProjects\AGENT\tests\unit\test_workflow_service.py`

- [ ] **Step 1: Extend unit tests to cover launch-time tenant policy and KB validation**

```python
def test_assemble_template_launch_rejects_missing_knowledge_base() -> None:
    with pytest.raises(ValueError, match="unknown knowledge base: kb-missing"):
        assemble_template_launch(
            tenant_id="tenant-a",
            template_id="wf-triage",
            template_name="Incident Triage",
            version=1,
            definition={
                "entrypoint": {"objective_template": "Triage {ticket_id}", "result_contract": "string"},
                "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                "tools": {"allowed_tools": ["rag_search"], "approval_required_tools": []},
                "knowledge": {"default_kb_ids": ["kb-missing"], "allow_kb_override": False},
                "runtime": {"max_turns": 4, "timeout_seconds": 60, "tags": []},
                "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
            },
            launch_input={"ticket_id": "INC-1"},
            tenant_allowed_tools=["rag_search"],
            tenant_approval_required_tools=[],
            existing_kb_ids=["kb-ops"],
        )
```

- [ ] **Step 2: Run the unit tests to verify service and assembler logic still fails**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py -v`
Expected: FAIL in launch validation or missing runtime integration methods.

- [ ] **Step 3: Implement workflow assembler, service, and template-aware run creation**

```python
def validate_template_definition(definition: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    objective_template = definition.get("entrypoint", {}).get("objective_template")
    if not isinstance(objective_template, str) or not objective_template.strip():
        errors.append("entrypoint.objective_template must be a non-empty string")

    worker_roles = definition.get("agents", {}).get("allowed_worker_roles", [])
    for worker_role in worker_roles:
        try:
            ensure_predefined_worker(AgentRole(worker_role))
        except Exception:
            errors.append(f"unsupported worker role: {worker_role}")

    return errors
```

```python
@dataclass(slots=True)
class AssembledTemplateLaunch:
    objective: str
    default_kb_ids: list[str]
    effective_allowed_tools: list[str]
    effective_approval_required_tools: list[str]
    workflow_policy: dict[str, Any]


def assemble_template_launch(
    *,
    tenant_id: str,
    template_id: str,
    template_name: str,
    version: int,
    definition: dict[str, Any],
    launch_input: dict[str, Any],
    tenant_allowed_tools: list[str],
    tenant_approval_required_tools: list[str],
    existing_kb_ids: list[str],
) -> AssembledTemplateLaunch:
    objective = definition["entrypoint"]["objective_template"].format_map(launch_input)
    kb_ids = list(definition.get("knowledge", {}).get("default_kb_ids", []))
    for kb_id in kb_ids:
        if kb_id not in existing_kb_ids:
            raise ValueError(f"unknown knowledge base: {kb_id}")

    allowed = sorted(set(tenant_allowed_tools).intersection(definition["tools"]["allowed_tools"]))
    if not allowed:
        raise ValueError("effective allowed tool policy is empty")

    approval_required = sorted(
        set(tenant_approval_required_tools).union(definition["tools"]["approval_required_tools"])
    )
    return AssembledTemplateLaunch(
        objective=objective,
        default_kb_ids=kb_ids,
        effective_allowed_tools=allowed,
        effective_approval_required_tools=approval_required,
        workflow_policy={
            "allowed_tools": allowed,
            "approval_required_tools": approval_required,
            "default_kb_ids": kb_ids,
        },
    )
```

```python
async def create_run_from_template_launch(
    self,
    *,
    tenant_id: str,
    objective: str,
    template_id: str,
    template_version: int,
    template_name: str,
    launch_input: dict[str, Any],
    effective_workflow_policy: dict[str, Any],
) -> RunRecord:
    run = await self.create_run(tenant_id, objective)
    await self._workflow_repository.create_run_link(
        WorkflowRunLinkRecord(
            run_id=run.run_id,
            tenant_id=tenant_id,
            template_id=template_id,
            template_version=template_version,
            template_name=template_name,
            launch_input=launch_input,
            effective_workflow_policy=effective_workflow_policy,
        )
    )
    return run
```

- [ ] **Step 4: Run the unit tests to verify validation and assembly pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/workflows/assembler.py src/agent_runtime/workflows/service.py src/agent_runtime/runtime/services.py tests/unit/test_workflow_service.py
git commit -m "feat: add workflow template launch assembly"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 4: Add Workflow Template API, App Wiring, And Integration Tests

**Files:**
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\routes\workflow_templates.py`
- Create: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\app.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\src\agent_runtime\api\schemas.py`

- [ ] **Step 1: Write the failing integration tests for template lifecycle and launch**

```python
@pytest.mark.asyncio
async def test_workflow_template_create_publish_and_launch(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {"supervisor": [ModelDecision(kind=DecisionKind.FINISH, summary="done", final_output="triaged")]}
        ),
        embedding_provider=FakeEmbeddingProvider(),
    )

    async with app_client_context(app) as client:
        await client.post("/internal/knowledge-bases", json={
            "kb_id": "kb-ops", "tenant_id": "tenant-a", "name": "Ops", "root_path": str(tmp_path / "kb")
        })
        await client.post("/v1/tenants/tenant-a/policies", json={
            "allowed_tools": ["rag_search"], "approval_required_tools": []
        })

        create_response = await client.post("/v1/workflow-templates", json={
            "template_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triages incidents",
            "definition": {
                "entrypoint": {"objective_template": "Triage {ticket_id}", "result_contract": "string"},
                "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                "tools": {"allowed_tools": ["rag_search"], "approval_required_tools": []},
                "knowledge": {"default_kb_ids": ["kb-ops"], "allow_kb_override": False},
                "runtime": {"max_turns": 6, "timeout_seconds": 300, "tags": ["ops"]},
                "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
            },
            "input_schema": {"type": "object", "required": ["ticket_id"]},
        })
        assert create_response.status_code == 201

        publish_response = await client.post("/v1/workflow-templates/wf-triage/versions/1/publish", json={"tenant_id": "tenant-a"})
        assert publish_response.status_code == 200

        launch_response = await client.post("/v1/workflow-templates/wf-triage/launch", json={
            "tenant_id": "tenant-a", "input": {"ticket_id": "INC-42"}
        })
        assert launch_response.status_code == 201
        assert launch_response.json()["workflow_template"]["template_id"] == "wf-triage"
```

- [ ] **Step 2: Run the integration tests to verify the route and app wiring fail first**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/integration/test_workflow_templates_api.py -v`
Expected: FAIL because the workflow template routes are not registered yet.

- [ ] **Step 3: Add the workflow template router and app wiring**

```python
router = APIRouter(prefix="/v1/workflow-templates", tags=["workflow-templates"])


@router.post("", response_model=WorkflowTemplateResponse, status_code=201)
async def create_workflow_template(request: Request, payload: WorkflowTemplateCreateRequest) -> WorkflowTemplateResponse:
    template = await request.app.state.workflow_service.create_template(payload)
    return WorkflowTemplateResponse.model_validate(template.model_dump())


@router.get("", response_model=list[WorkflowTemplateResponse])
async def list_workflow_templates(request: Request, tenant_id: str) -> list[WorkflowTemplateResponse]:
    templates = await request.app.state.workflow_service.list_templates(tenant_id)
    return [WorkflowTemplateResponse.model_validate(item.model_dump()) for item in templates]


@router.post("/{template_id}/versions/{version}/publish", response_model=WorkflowTemplateResponse)
async def publish_workflow_template_version(
    request: Request,
    template_id: str,
    version: int,
    payload: WorkflowTemplatePublishRequest,
) -> WorkflowTemplateResponse:
    template = await request.app.state.workflow_service.publish_template_version(
        tenant_id=payload.tenant_id,
        template_id=template_id,
        version=version,
    )
    return WorkflowTemplateResponse.model_validate(template.model_dump())


@router.post("/{template_id}/launch", response_model=WorkflowTemplateLaunchResponse, status_code=201)
async def launch_workflow_template(
    request: Request,
    template_id: str,
    payload: WorkflowTemplateLaunchRequest,
) -> WorkflowTemplateLaunchResponse:
    run, workflow_metadata = await request.app.state.workflow_service.launch_template(
        tenant_id=payload.tenant_id,
        template_id=template_id,
        version=payload.version,
        launch_input=payload.input,
        metadata=payload.metadata,
    )
    return WorkflowTemplateLaunchResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
        workflow_template=workflow_metadata,
    )
```

```python
workflow_repository = WorkflowRepository(session_factory)
run_service = RunService(
    repository,
    model_client or ScriptedModelClient({"supervisor": []}),
    event_hub,
    tool_gateway=tool_gateway,
    metrics_sink=metrics_sink,
    runtime_logger=runtime_logger,
    fault_injector=runtime_fault_injector,
    workflow_repository=workflow_repository,
)
workflow_service = WorkflowService(
    workflow_repository=workflow_repository,
    runtime_repository=repository,
    knowledge_repository=knowledge_repository,
    run_service=run_service,
)
app.state.workflow_service = workflow_service
app.state.run_service = run_service
app.include_router(workflow_templates_router)
```

- [ ] **Step 4: Run the integration tests to verify template lifecycle and launch pass**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/integration/test_workflow_templates_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_runtime/api/routes/workflow_templates.py src/agent_runtime/api/app.py src/agent_runtime/api/schemas.py tests/integration/test_workflow_templates_api.py
git commit -m "feat: add workflow template management api"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

### Task 5: Add Approval And Retrieval Guardrail Coverage, Then Run Full Verification

**Files:**
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\tests\integration\test_workflow_templates_api.py`
- Modify: `C:\Users\Ilya\PycharmProjects\AGENT\docs\deferred-roadmap.md` only if implementation changes any deferred classification

- [ ] **Step 1: Add integration cases for approval-gated launch and missing KB rejection**

```python
@pytest.mark.asyncio
async def test_workflow_template_launch_rejects_unknown_kb_binding(tmp_path: Path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient({"supervisor": []}),
        embedding_provider=FakeEmbeddingProvider(),
    )
    async with app_client_context(app) as client:
        await client.post("/v1/tenants/tenant-a/policies", json={
            "allowed_tools": ["rag_search"],
            "approval_required_tools": [],
        })
        await client.post("/v1/workflow-templates", json={
            "template_id": "wf-triage",
            "tenant_id": "tenant-a",
            "name": "Incident Triage",
            "description": "Triages incidents",
            "definition": {
                "entrypoint": {"objective_template": "Triage {ticket_id}", "result_contract": "string"},
                "agents": {"allowed_worker_roles": ["researcher"], "max_worker_count": 1},
                "tools": {"allowed_tools": ["rag_search"], "approval_required_tools": []},
                "knowledge": {"default_kb_ids": ["kb-missing"], "allow_kb_override": False},
                "runtime": {"max_turns": 6, "timeout_seconds": 300, "tags": ["ops"]},
                "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
            },
            "input_schema": {"type": "object", "required": ["ticket_id"]},
        })
        await client.post("/v1/workflow-templates/wf-triage/versions/1/publish", json={"tenant_id": "tenant-a"})
    launch_response = await client.post("/v1/workflow-templates/wf-triage/launch", json={
        "tenant_id": "tenant-a", "input": {"ticket_id": "INC-404"}
    })
    assert launch_response.status_code == 422
    assert "unknown knowledge base" in launch_response.text


@pytest.mark.asyncio
async def test_workflow_template_launch_preserves_approval_pause_and_resume(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register("payment-api", StaticExecutor())
    app = await _build_approval_app(tmp_path, finish_after_tool=True)
    async with app_client_context(app) as client:
        await client.post("/v1/workflow-templates", json={
            "template_id": "wf-pay",
            "tenant_id": "tenant-a",
            "name": "Payment Workflow",
            "description": "Launches approval-gated payment",
            "definition": {
                "entrypoint": {"objective_template": "Submit payment for {ticket_id}", "result_contract": "string"},
                "agents": {"allowed_worker_roles": [], "max_worker_count": 0},
                "tools": {"allowed_tools": ["payment-api"], "approval_required_tools": ["payment-api"]},
                "knowledge": {"default_kb_ids": [], "allow_kb_override": False},
                "runtime": {"max_turns": 4, "timeout_seconds": 300, "tags": ["payments"]},
                "launch_policy": {"allow_input_objective_override": False, "require_published_version": True},
            },
            "input_schema": {"type": "object", "required": ["ticket_id"]},
        })
        await client.post("/v1/workflow-templates/wf-pay/versions/1/publish", json={"tenant_id": "tenant-a"})
    launch_response = await client.post("/v1/workflow-templates/wf-pay/launch", json={
        "tenant_id": "tenant-a", "input": {"ticket_id": "INC-7"}
    })
    assert launch_response.status_code == 201
    run_id = launch_response.json()["run_id"]
    for _ in range(20):
        status_payload = (await client.get(f"/v1/runs/{run_id}")).json()
        if status_payload["status"] == "waiting_for_approval":
            break
        await asyncio.sleep(0.05)
    assert status_payload["status"] == "waiting_for_approval"
```

- [ ] **Step 2: Run the focused workflow template suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest tests/unit/test_workflow_service.py tests/integration/test_workflow_templates_api.py -v`
Expected: PASS

- [ ] **Step 3: Run the full test suite**

Run: `C:\Users\Ilya\anaconda3\envs\agent_rag\python.exe -m pytest -v`
Expected: PASS

- [ ] **Step 4: Re-check spec and deferred roadmap alignment**

Run: `rg -n "workflow template|visual workflow|API-first|tracing|external vector|semantic chunk|startup-instruction|aiosqlite" docs/superpowers/specs/2026-05-18-agent-runtime-workflow-template-layer-design.md docs/deferred-roadmap.md`
Expected: the implemented phase remains template-first and deferred items stay explicitly documented.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_workflow_service.py tests/integration/test_workflow_templates_api.py docs/deferred-roadmap.md
git commit -m "test: verify workflow template layer end to end"
```

Current workflow note: skip the `git commit` command unless commit execution is later requested.

## Self-Review

- Spec coverage:
  - template asset lifecycle: covered by Tasks 1, 2, and 4
  - immutable published versions: covered by Tasks 2 and 3
  - launch-time objective assembly and policy composition: covered by Task 3
  - template-based run launch API: covered by Task 4
  - approval and RAG guardrails: covered by Task 5

- Placeholder scan:
  - All task steps include concrete file paths, commands, and code shapes.
  - Commit steps are preserved for workflow parity, but the current workspace note explicitly says not to execute them unless later requested.

- Type consistency:
  - Repository, service, and API layers all use `template_id`, `version`, and `WorkflowRunLinkRecord`.
  - Launch response metadata consistently uses `workflow_template`.
