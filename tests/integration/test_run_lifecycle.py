import asyncio

import pytest
from httpx import AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import AgentRole, AgentStatus, DecisionKind, RunStatus
from agent_runtime.domain.models import AgentRecord, CheckpointRecord, RunRecord, RuntimeEvent
from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.testing.faults import FaultPoint, FaultRule, RuleBasedFaultInjector
from tests.conftest import app_client_context


class BlockingModelClient(ModelClient):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        self.started.set()
        await self.release.wait()
        return ModelDecision(
            kind=DecisionKind.FINISH,
            summary="done",
            final_output="late answer",
        )


class FailingModelClient(ModelClient):
    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        raise RuntimeError(f"model exploded for {turn.run_id}")


@pytest.mark.asyncio
async def test_create_run_completes_and_replays_events(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="final answer",
                    )
                ]
            }
        ),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "summarize incident"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        assert payload["status"] == "completed"
        assert payload["result"] == "final answer"

        events_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        assert events_response.status_code == 200
        event_types = [item["event_type"] for item in events_response.json()["events"]]
        assert event_types[0] == "run.created"
        assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_run_lifecycle_updates_metrics_endpoint(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="ok",
                    )
                ]
            }
        ),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "observe"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        metrics_response = await client.get("/metrics")

    assert payload["status"] == "completed"
    assert metrics_response.status_code == 200
    assert "runtime_runs_created_total" in metrics_response.text
    assert "runtime_runs_completed_total" in metrics_response.text


@pytest.mark.asyncio
async def test_event_stream_hub_replays_persisted_events_before_live_events() -> None:
    persisted_event = RuntimeEvent.build(
        tenant_id="tenant-a",
        run_id="run-1",
        event_type="run.created",
        payload={"objective": "summarize incident"},
        agent_id="agent-1",
    )
    live_event = RuntimeEvent.build(
        tenant_id="tenant-a",
        run_id="run-1",
        event_type="run.completed",
        payload={"result": "final answer"},
    )

    async def load_events(run_id: str) -> list[RuntimeEvent]:
        assert run_id == "run-1"
        return [persisted_event]

    hub = EventStreamHub(load_events)
    stream = hub.stream("run-1")

    first_event = await anext(stream)
    assert first_event.event_type == "run.created"

    publish_task = asyncio.create_task(hub.publish(live_event))
    second_event = await asyncio.wait_for(anext(stream), timeout=1)
    await publish_task

    assert second_event.event_type == "run.completed"
    await stream.aclose()


@pytest.mark.asyncio
async def test_cancelled_run_does_not_later_complete(tmp_path) -> None:
    model_client = BlockingModelClient()
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=model_client,
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "summarize incident"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        await asyncio.wait_for(model_client.started.wait(), timeout=1)

        cancel_response = await client.post(f"/v1/runs/{run_id}/cancel")
        assert cancel_response.status_code == 202

        model_client.release.set()

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "cancelled":
                break
            await asyncio.sleep(0.05)

        assert payload["status"] == "cancelled"
        assert payload["result"] is None

        await asyncio.sleep(0.2)
        final_status = await client.get(f"/v1/runs/{run_id}")
        assert final_status.json()["status"] == "cancelled"

        events_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        event_types = [item["event_type"] for item in events_response.json()["events"]]
        assert "run.cancelled" in event_types
        assert "run.completed" not in event_types


@pytest.mark.asyncio
async def test_model_failure_marks_run_failed_and_emits_event(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=FailingModelClient(),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "summarize incident"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "failed":
                break
            await asyncio.sleep(0.05)

        assert payload["status"] == "failed"
        assert "model exploded" in payload["error"]

        events_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        event_types = [item["event_type"] for item in events_response.json()["events"]]
        assert event_types[-1] == "run.failed"


@pytest.mark.asyncio
async def test_injected_model_failure_marks_run_failed(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="ok",
                    )
                ]
            }
        ),
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.MODEL_BEFORE_COMPLETE,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected model failure"),
                )
            ]
        ),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "observe"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "failed":
                break
            await asyncio.sleep(0.05)

    assert payload["status"] == RunStatus.FAILED.value
    assert "injected model failure" in payload["error"]


@pytest.mark.asyncio
async def test_resume_endpoint_completes_checkpointed_run(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
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
    )
    await app.state.ensure_initialized()

    repository = app.state.run_service._repository
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

    async with app_client_context(app) as client:
        response = await client.post(f"/v1/runs/{run.run_id}/resume")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["result"] == "resume complete"

        replay_response = await client.get(f"/v1/runs/{run.run_id}/events/replay")
        assert replay_response.status_code == 200
        event_types = [item["event_type"] for item in replay_response.json()["events"]]
        assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_injected_resume_entry_failure_marks_run_failed(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
            {
                "supervisor": [
                    ModelDecision(
                        kind=DecisionKind.FINISH,
                        summary="done",
                        final_output="ok",
                    )
                ]
            }
        ),
        fault_injector=RuleBasedFaultInjector(
            [
                FaultRule(
                    point=FaultPoint.RUN_RESUME_BEFORE_EXECUTE,
                    times=1,
                    exception_factory=lambda: RuntimeError("injected resume failure"),
                )
            ]
        ),
    )
    await app.state.ensure_initialized()

    async with app_client_context(app) as client:
        repository = app.state.run_service._repository
        run = RunRecord(tenant_id="tenant-a", objective="recover this run", status=RunStatus.RUNNING)
        supervisor = AgentRecord(
            run_id=run.run_id,
            role=AgentRole.SUPERVISOR,
            objective=run.objective,
            status=AgentStatus.REASONING,
        )
        await repository.create_run(run, supervisor)
        response = await client.post(f"/v1/runs/{run.run_id}/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "injected resume failure" in response.json()["error"]


@pytest.mark.asyncio
async def test_missing_run_endpoints_return_404(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        for path, method in (
            ("/v1/runs/missing-run-id/resume", client.post),
            ("/v1/runs/missing-run-id/cancel", client.post),
            ("/v1/runs/missing-run-id/events", client.get),
            ("/v1/runs/missing-run-id/events/replay", client.get),
        ):
            response = await method(path)
            assert response.status_code == 404


@pytest.mark.asyncio
async def test_event_stream_hub_skips_duplicate_live_event_seen_during_replay() -> None:
    persisted_event = RuntimeEvent.build(
        tenant_id="tenant-a",
        run_id="run-1",
        event_type="run.created",
        payload={"objective": "summarize incident"},
        agent_id="agent-1",
    )
    duplicate_event = RuntimeEvent.model_validate(persisted_event.model_dump())

    release_load = asyncio.Event()

    async def load_events(run_id: str) -> list[RuntimeEvent]:
        assert run_id == "run-1"
        await release_load.wait()
        return [persisted_event]

    hub = EventStreamHub(load_events)
    stream = hub.stream("run-1")

    first_event_task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await hub.publish(duplicate_event)
    release_load.set()

    first_event = await asyncio.wait_for(first_event_task, timeout=1)
    assert first_event.event_id == persisted_event.event_id

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.1)

    await stream.aclose()
