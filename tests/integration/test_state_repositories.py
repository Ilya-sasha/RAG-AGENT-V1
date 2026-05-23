from datetime import UTC

import pytest
from sqlalchemy.exc import IntegrityError

from agent_runtime.domain.enums import AgentRole, AgentStatus, EventType, RunStatus, TaskStatus
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RunRecord, RuntimeEvent, TaskRecord
from agent_runtime.state.db import build_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_repository_round_trip_covers_runs_agents_tasks_events_and_checkpoints(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)

    run = RunRecord(tenant_id="tenant-a", objective="summarize")
    supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=run.objective)
    await repository.create_run(run, supervisor)

    worker = AgentRecord(
        run_id=run.run_id,
        role=AgentRole.RESEARCHER,
        objective="research facts",
        parent_agent_id=supervisor.agent_id,
    )
    await repository.add_agent(worker)

    event = RuntimeEvent.build(
        tenant_id=run.tenant_id,
        run_id=run.run_id,
        event_type=EventType.RUN_CREATED,
        payload={"objective": run.objective},
        agent_id=supervisor.agent_id,
    )
    await repository.append_event(event)

    checkpoint = CheckpointRecord(
        run_id=run.run_id,
        agent_id=supervisor.agent_id,
        step_name="before_model",
        payload={"observations": []},
    )
    await repository.save_checkpoint(checkpoint)

    task = TaskRecord(
        run_id=run.run_id,
        parent_agent_id=supervisor.agent_id,
        worker_agent_id=worker.agent_id,
        worker_role=worker.role,
        objective="collect sources",
    )
    await repository.add_task(task)

    await repository.update_run_status(run.run_id, RunStatus.RUNNING)
    await repository.update_agent_state(
        worker.agent_id,
        status=AgentStatus.REASONING,
        observations=["found primary source"],
    )
    await repository.update_task_state(
        task.task_id,
        status=TaskStatus.COMPLETED,
        result="collected sources",
    )

    active_run = RunRecord(tenant_id="tenant-a", objective="keep running")
    active_supervisor = AgentRecord(
        run_id=active_run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=active_run.objective,
    )
    await repository.create_run(active_run, active_supervisor)

    completed_run = RunRecord(tenant_id="tenant-a", objective="done")
    completed_supervisor = AgentRecord(
        run_id=completed_run.run_id,
        role=AgentRole.SUPERVISOR,
        objective=completed_run.objective,
    )
    await repository.create_run(completed_run, completed_supervisor)
    await repository.update_run_status(
        completed_run.run_id,
        RunStatus.COMPLETED,
        result="finished",
    )

    stored_run = await repository.get_run(run.run_id)
    stored_worker = await repository.get_agent(worker.agent_id)
    stored_agents = await repository.list_agents(run.run_id)
    stored_events = await repository.list_events(run.run_id)
    stored_tasks = await repository.list_tasks(run.run_id)
    latest_checkpoint = await repository.get_latest_checkpoint(run.run_id, supervisor.agent_id)
    active_runs = await repository.list_active_runs()

    assert stored_run is not None
    assert stored_run.status == RunStatus.RUNNING
    assert stored_run.updated_at.tzinfo == UTC
    assert stored_run.created_at.tzinfo == UTC

    assert stored_worker is not None
    assert stored_worker.status == AgentStatus.REASONING
    assert stored_worker.observations == ["found primary source"]
    assert stored_worker.parent_agent_id == supervisor.agent_id
    assert stored_worker.created_at.tzinfo == UTC
    assert stored_worker.updated_at.tzinfo == UTC

    assert [agent.agent_id for agent in stored_agents] == [supervisor.agent_id, worker.agent_id]

    assert len(stored_events) == 1
    assert stored_events[0].event_type == EventType.RUN_CREATED
    assert stored_events[0].created_at.tzinfo == UTC

    assert len(stored_tasks) == 1
    assert stored_tasks[0].task_id == task.task_id
    assert stored_tasks[0].status == TaskStatus.COMPLETED
    assert stored_tasks[0].result == "collected sources"
    assert stored_tasks[0].created_at.tzinfo == UTC
    assert stored_tasks[0].updated_at.tzinfo == UTC

    assert latest_checkpoint is not None
    assert latest_checkpoint.step_name == "before_model"
    assert latest_checkpoint.created_at.tzinfo == UTC

    assert {active.run_id for active in active_runs} == {run.run_id, active_run.run_id}
    assert all(active.status in {RunStatus.CREATED, RunStatus.RUNNING, RunStatus.PAUSED} for active in active_runs)


@pytest.mark.asyncio
async def test_repository_rejects_invalid_foreign_key_references(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)

    invalid_agent = AgentRecord(
        run_id="missing-run",
        role=AgentRole.RESEARCHER,
        objective="orphan agent",
    )

    with pytest.raises(IntegrityError):
        await repository.add_agent(invalid_agent)


@pytest.mark.asyncio
async def test_repository_marks_run_failed_and_appends_terminal_event_atomically(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    await init_db(session_factory)
    repository = RuntimeRepository(session_factory)

    run = RunRecord(tenant_id="tenant-a", objective="summarize")
    supervisor = AgentRecord(run_id=run.run_id, role=AgentRole.SUPERVISOR, objective=run.objective)
    await repository.create_run(run, supervisor)
    await repository.update_run_status(run.run_id, RunStatus.RUNNING)

    failed_event = RuntimeEvent.build(
        tenant_id=run.tenant_id,
        run_id=run.run_id,
        agent_id=supervisor.agent_id,
        event_type=EventType.RUN_FAILED,
        payload={"error": "model exploded"},
    )

    await repository.mark_run_failed(
        run_id=run.run_id,
        error="model exploded",
        event=failed_event,
        failed_agent_id=supervisor.agent_id,
    )

    stored_run = await repository.get_run(run.run_id)
    stored_agent = await repository.get_agent(supervisor.agent_id)
    stored_events = await repository.list_events(run.run_id)

    assert stored_run is not None
    assert stored_run.status == RunStatus.FAILED
    assert stored_run.error == "model exploded"

    assert stored_agent is not None
    assert stored_agent.status == AgentStatus.FAILED

    assert stored_events[-1].event_type == EventType.RUN_FAILED
    assert stored_events[-1].payload == {"error": "model exploded"}
