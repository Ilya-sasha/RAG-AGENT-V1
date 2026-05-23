from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput


class ScriptedModelClient(ModelClient):
    def __init__(self, scripts: Mapping[str, Sequence[ModelDecision]]) -> None:
        self._scripts = {role: list(decisions) for role, decisions in scripts.items()}
        self._offsets: dict[tuple[str, str], int] = defaultdict(int)

    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        role_key = turn.agent_role.value
        decisions = self._scripts.get(role_key, [])
        cursor_key = (role_key, turn.agent_id or role_key)
        index = self._offsets[cursor_key]

        if index >= len(decisions):
            raise RuntimeError(
                f"no scripted decision remaining for role={role_key} agent_id={turn.agent_id}"
            )

        self._offsets[cursor_key] += 1
        return decisions[index]
