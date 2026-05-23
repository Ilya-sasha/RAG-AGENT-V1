import pytest
from pydantic import ValidationError

from agent_runtime.domain.enums import AgentRole, DecisionKind, EventType
from agent_runtime.domain.models import RuntimeEvent
from agent_runtime.models.base import ModelDecision, ModelTurnInput
from agent_runtime.models.scripted import ScriptedModelClient


def test_runtime_event_builds_with_expected_fields() -> None:
    event = RuntimeEvent.build(
        tenant_id="tenant-a",
        run_id="run-1",
        event_type=EventType.RUN_CREATED,
        payload={"objective": "summarize"},
    )

    assert event.tenant_id == "tenant-a"
    assert event.run_id == "run-1"
    assert event.event_type == EventType.RUN_CREATED
    assert event.payload == {"objective": "summarize"}
    assert event.event_id


@pytest.mark.asyncio
async def test_scripted_model_client_returns_role_specific_decisions_in_order() -> None:
    client = ScriptedModelClient(
        {
            "supervisor": [
                ModelDecision(
                    kind=DecisionKind.DELEGATE,
                    summary="delegate",
                    worker_role=AgentRole.RESEARCHER,
                    task_input="gather facts",
                ),
                ModelDecision(
                    kind=DecisionKind.FINISH,
                    summary="finish",
                    final_output="done",
                ),
            ]
        }
    )

    turn = ModelTurnInput(
        run_id="run-1",
        agent_id="agent-1",
        agent_role=AgentRole.SUPERVISOR,
        objective="handle request",
        observations=[],
    )

    first = await client.complete(turn)
    second = await client.complete(turn)

    assert first.kind == DecisionKind.DELEGATE
    assert first.worker_role == AgentRole.RESEARCHER
    assert second.kind == DecisionKind.FINISH
    assert second.final_output == "done"


@pytest.mark.asyncio
async def test_scripted_model_client_tracks_offsets_per_agent_for_same_role() -> None:
    client = ScriptedModelClient(
        {
            "supervisor": [
                ModelDecision(
                    kind=DecisionKind.DELEGATE,
                    summary="delegate",
                    worker_role=AgentRole.RESEARCHER,
                    task_input="gather facts",
                ),
                ModelDecision(
                    kind=DecisionKind.FINISH,
                    summary="finish",
                    final_output="done",
                ),
            ]
        }
    )
    first_turn = ModelTurnInput(
        run_id="run-1",
        agent_id="agent-1",
        agent_role=AgentRole.SUPERVISOR,
        objective="handle request",
        observations=[],
    )
    second_turn = ModelTurnInput(
        run_id="run-1",
        agent_id="agent-2",
        agent_role=AgentRole.SUPERVISOR,
        objective="handle another request",
        observations=[],
    )

    first_agent_first = await client.complete(first_turn)
    second_agent_first = await client.complete(second_turn)
    first_agent_second = await client.complete(first_turn)

    assert first_agent_first.kind == DecisionKind.DELEGATE
    assert second_agent_first.kind == DecisionKind.DELEGATE
    assert first_agent_second.kind == DecisionKind.FINISH


@pytest.mark.asyncio
async def test_scripted_model_client_raises_when_agent_script_is_exhausted() -> None:
    client = ScriptedModelClient(
        {
            "supervisor": [
                ModelDecision(
                    kind=DecisionKind.FINISH,
                    summary="finish",
                    final_output="done",
                )
            ]
        }
    )
    turn = ModelTurnInput(
        run_id="run-1",
        agent_id="agent-1",
        agent_role=AgentRole.SUPERVISOR,
        objective="handle request",
        observations=[],
    )

    first = await client.complete(turn)

    assert first.kind == DecisionKind.FINISH

    with pytest.raises(RuntimeError, match="no scripted decision remaining"):
        await client.complete(turn)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "kind": DecisionKind.FINISH,
                "summary": "missing output",
            },
            "final_output",
        ),
        (
            {
                "kind": DecisionKind.FINISH,
                "summary": "has delegation fields",
                "final_output": "done",
                "worker_role": AgentRole.RESEARCHER,
                "task_input": "gather facts",
            },
            "worker_role/task_input",
        ),
        (
            {
                "kind": DecisionKind.DELEGATE,
                "summary": "missing worker inputs",
            },
            "worker_role/task_input",
        ),
        (
            {
                "kind": DecisionKind.DELEGATE,
                "summary": "has final output",
                "worker_role": AgentRole.RESEARCHER,
                "task_input": "gather facts",
                "final_output": "done",
            },
            "final_output",
        ),
    ],
)
def test_model_decision_rejects_invalid_payload_combinations(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ModelDecision(**kwargs)
