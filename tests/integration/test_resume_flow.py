import pytest
import asyncio

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import AgentRole, AgentStatus, DecisionKind, RunStatus
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RunRecord, TaskRecord
from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.runtime.resume import ResumeCoordinator
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_resume_coordinator_continues_from_latest_checkpoint(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)
    event_hub = EventStreamHub(repository.list_events)

    run = RunRecord(tenant_id="tenant-a", objective="recover this run", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.REASONING,
    )
    await repository.create_run(run, supervisor)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": ["checkpoint recovered"]},
        )
    )

    orchestrator = RuntimeOrchestrator(
        repository=repository,
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="recovered",
                        final_output="resume complete",
                    )
                ]
            }
        ),
        event_hub=event_hub,
    )
    coordinator = ResumeCoordinator(repository, orchestrator)

    await coordinator.resume_run(run.run_id)

    stored_run = await repository.get_run(run.run_id)
    stored_agent = await repository.get_agent(supervisor.agent_id)
    latest_checkpoint = await repository.get_latest_checkpoint(run.run_id, supervisor.agent_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.COMPLETED
    assert stored_run.result == "resume complete"

    assert stored_agent is not None
    assert stored_agent.status == AgentStatus.COMPLETED
    assert stored_agent.observations == ["checkpoint recovered"]

    assert latest_checkpoint is not None
    assert latest_checkpoint.step_name == "completed"
    assert latest_checkpoint.payload["observations"] == ["checkpoint recovered"]
    assert latest_checkpoint.payload["result"] == "resume complete"


@pytest.mark.asyncio
async def test_app_startup_skips_active_runs_by_default(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="recovered on startup",
                        final_output="startup resume complete",
                    )
                ]
            }
        ),
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    run = RunRecord(tenant_id="tenant-a", objective="recover on startup", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.REASONING,
    )
    await repository.create_run(run, supervisor)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": ["startup checkpoint"]},
        )
    )

    async with app.router.lifespan_context(app):
        stored_run = await repository.get_run(run.run_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.RUNNING
    assert stored_run.result is None


@pytest.mark.asyncio
async def test_app_startup_resumes_active_runs_when_explicitly_enabled(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="recovered on startup",
                        final_output="startup resume complete",
                    )
                ]
            }
        ),
        resume_active_runs_on_startup=True,
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    run = RunRecord(tenant_id="tenant-a", objective="recover on startup", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.REASONING,
    )
    await repository.create_run(run, supervisor)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": ["startup checkpoint"]},
        )
    )

    async with app.router.lifespan_context(app):
        stored_run = await repository.get_run(run.run_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.COMPLETED
    assert stored_run.result == "startup resume complete"


@pytest.mark.asyncio
async def test_app_startup_marks_waiting_on_tool_runs_failed_when_resume_is_enabled(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=HangingModelClient(),
        resume_active_runs_on_startup=True,
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    run = RunRecord(tenant_id="tenant-a", objective="dangerous startup recovery", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.WAITING_ON_TOOL,
    )
    await repository.create_run(run, supervisor)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": ["startup checkpoint"]},
        )
    )

    async with app.router.lifespan_context(app):
        stored_run = await repository.get_run(run.run_id)
        stored_agent = await repository.get_agent(supervisor.agent_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.FAILED
    assert "startup recovery" in (stored_run.error or "")
    assert stored_agent is not None
    assert stored_agent.status == AgentStatus.FAILED


class HangingModelClient(ModelClient):
    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_app_startup_does_not_block_on_active_run_recovery(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=HangingModelClient(),
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
    run = RunRecord(tenant_id="tenant-a", objective="recover without blocking startup", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.REASONING,
    )
    await repository.create_run(run, supervisor)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="before_model",
            payload={"observations": ["startup checkpoint"]},
        )
    )

    lifespan = app.router.lifespan_context(app)
    await asyncio.wait_for(lifespan.__aenter__(), timeout=1)
    try:
        stored_run = await repository.get_run(run.run_id)
        assert stored_run is not None
        assert stored_run.status == RunStatus.RUNNING
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_resume_coordinator_reuses_existing_worker_dispatch_without_duplication(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)
    event_hub = EventStreamHub(repository.list_events)

    run = RunRecord(tenant_id="tenant-a", objective="investigate alert", status=RunStatus.RUNNING)
    supervisor = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=run.objective,
        status=AgentStatus.WAITING_ON_WORKERS,
    )
    await repository.create_run(run, supervisor)

    worker = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.RESEARCHER,
        objective="collect incident facts",
        status=AgentStatus.READY,
        parent_agent_id=supervisor.agent_id,
    )
    await repository.add_agent(worker)

    task = TaskRecord(
        run_id=run.run_id,
        parent_agent_id=supervisor.agent_id,
        worker_agent_id=worker.agent_id,
        worker_role=worker.role,
        objective=worker.objective,
    )
    await repository.add_task(task)
    await repository.save_checkpoint(
        CheckpointRecord(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            step_name="after_dispatch",
            payload={
                "observations": [],
                "task_id": task.task_id,
                "worker_agent_id": worker.agent_id,
            },
        )
    )

    model_client = ScriptedModelClient(
        {
            "supervisor": [
                ModelDecision(
                    kind=DecisionKind.DELEGATE,
                    summary="delegate research",
                    worker_role=AgentRole.RESEARCHER,
                    task_input="collect incident facts",
                ),
                ModelDecision(
                    kind=DecisionKind.FINISH,
                    summary="finish with worker evidence",
                    final_output="incident summary with worker evidence",
                ),
            ],
            "researcher": [
                ModelDecision(
                    kind=DecisionKind.FINISH,
                    summary="worker complete",
                    final_output="facts collected",
                )
            ],
        }
    )
    await model_client.complete(
        ModelTurnInput(
            run_id=run.run_id,
            agent_id=supervisor.agent_id,
            agent_role=supervisor.role,
            objective=supervisor.objective,
            observations=[],
        )
    )

    orchestrator = RuntimeOrchestrator(
        repository=repository,
        model_client=model_client,
        event_hub=event_hub,
    )
    coordinator = ResumeCoordinator(repository, orchestrator)

    await coordinator.resume_run(run.run_id)

    stored_run = await repository.get_run(run.run_id)
    agents = await repository.list_agents(run.run_id)
    tasks = await repository.list_tasks(run.run_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.COMPLETED
    assert stored_run.result == "incident summary with worker evidence"
    assert len(agents) == 2
    assert len(tasks) == 1
    assert tasks[0].result == "facts collected"
