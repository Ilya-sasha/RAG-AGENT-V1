from __future__ import annotations

from agent_runtime.runtime.orchestrator import RuntimeOrchestrator
from agent_runtime.state.repositories import RuntimeRepository


class ResumeCoordinator:
    def __init__(
        self,
        repository: RuntimeRepository,
        orchestrator: RuntimeOrchestrator,
    ) -> None:
        self._repository = repository
        self._orchestrator = orchestrator

    async def resume_run(self, run_id: str) -> None:
        await self._orchestrator.execute_run(run_id)

    async def resume_active_runs(self) -> None:
        for run in await self._repository.list_active_runs():
            await self._orchestrator.execute_run(run.run_id)
