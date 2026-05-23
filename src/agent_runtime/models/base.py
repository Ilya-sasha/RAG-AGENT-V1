from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from agent_runtime.domain.enums import AgentRole, DecisionKind


class ModelTurnInput(BaseModel):
    run_id: str
    agent_id: str
    agent_role: AgentRole
    objective: str
    observations: list[str] = Field(default_factory=list)


class ModelDecision(BaseModel):
    kind: DecisionKind
    summary: str
    final_output: str | None = None
    worker_role: AgentRole | None = None
    task_input: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "ModelDecision":
        if self.kind == DecisionKind.FINISH:
            if self.final_output is None:
                raise ValueError("final_output is required for finish decisions")
            if self.worker_role is not None or self.task_input is not None:
                raise ValueError(
                    "worker_role/task_input are not allowed for finish decisions"
                )

        if self.kind == DecisionKind.DELEGATE:
            if self.worker_role is None or self.task_input is None:
                raise ValueError(
                    "worker_role/task_input are required for delegate decisions"
                )
            if self.final_output is not None:
                raise ValueError("final_output is not allowed for delegate decisions")
            if self.tool_name is not None or self.tool_arguments is not None:
                raise ValueError("tool_name/tool_arguments are not allowed for delegate decisions")

        if self.kind == DecisionKind.CALL_TOOL:
            if self.tool_name is None or self.tool_arguments is None:
                raise ValueError("tool_name/tool_arguments are required for call_tool decisions")
            if self.final_output is not None:
                raise ValueError("final_output is not allowed for call_tool decisions")
            if self.worker_role is not None or self.task_input is not None:
                raise ValueError("worker_role/task_input are not allowed for call_tool decisions")

        return self


class ModelClient(Protocol):
    async def complete(self, turn: ModelTurnInput) -> ModelDecision: ...
