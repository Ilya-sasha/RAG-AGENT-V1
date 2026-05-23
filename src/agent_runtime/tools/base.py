from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from agent_runtime.domain.enums import ToolInvocationStatus


class ToolExecutionRequest(BaseModel):
    tenant_id: str
    run_id: str
    agent_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionOutcome(BaseModel):
    invocation_id: str
    status: ToolInvocationStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    requires_approval: bool = False
    approval_id: str | None = None


class ToolExecutor(Protocol):
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...
