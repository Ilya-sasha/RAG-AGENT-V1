from __future__ import annotations

from agent_runtime.domain.models import ApprovalRequestRecord
from agent_runtime.state.repositories import RuntimeRepository


class ApprovalService:
    def __init__(self, repository: RuntimeRepository) -> None:
        self._repository = repository

    async def request_tool_approval(
        self,
        *,
        tenant_id: str,
        run_id: str,
        agent_id: str,
        tool_name: str,
        reason: str,
    ) -> ApprovalRequestRecord:
        approval = ApprovalRequestRecord(
            tenant_id=tenant_id,
            run_id=run_id,
            agent_id=agent_id,
            tool_name=tool_name,
            reason=reason,
        )
        await self._repository.create_approval_request(approval)
        return approval
