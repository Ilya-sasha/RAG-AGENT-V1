import asyncio

import pytest
from httpx import AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import AgentRole, DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient
from tests.conftest import app_client_context


@pytest.mark.asyncio
async def test_supervisor_dispatches_worker_and_merges_result(tmp_path) -> None:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=ScriptedModelClient(
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
        ),
    )

    async with app_client_context(app) as client:
        create_response = await client.post(
            "/v1/runs",
            json={"tenant_id": "tenant-a", "objective": "investigate alert"},
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["run_id"]

        for _ in range(20):
            status_response = await client.get(f"/v1/runs/{run_id}")
            payload = status_response.json()
            if payload["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        replay_response = await client.get(f"/v1/runs/{run_id}/events/replay")
        metrics_response = await client.get("/metrics")
        assert replay_response.status_code == 200
        event_types = [event["event_type"] for event in replay_response.json()["events"]]

        assert payload["status"] == "completed"
        assert payload["result"] == "incident summary with worker evidence"
        assert "runtime_agent_decisions_total" in metrics_response.text
        assert 'kind="delegate"' in metrics_response.text
        assert 'kind="finish"' in metrics_response.text
        assert "task.dispatched" in event_types
        assert event_types.count("agent.completed") == 2
