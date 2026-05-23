from __future__ import annotations

from agent_runtime.tools.base import ToolExecutor


class ToolRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, ToolExecutor] = {}

    def register(self, tool_name: str, executor: ToolExecutor) -> None:
        self._executors[tool_name] = executor

    def get(self, tool_name: str) -> ToolExecutor:
        executor = self._executors.get(tool_name)
        if executor is None:
            raise RuntimeError(f"tool executor not registered: {tool_name}")
        return executor
