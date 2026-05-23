from __future__ import annotations

import re

from agent_runtime.approvals.service import ApprovalService
from agent_runtime.domain.enums import ToolInvocationStatus
from agent_runtime.domain.models import ToolInvocationRecord
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.tenancy.policies import evaluate_tool_policy
from agent_runtime.tools.base import ToolExecutionOutcome, ToolExecutionRequest
from agent_runtime.tools.registry import ToolRegistry


class ToolGateway:
    _PLACEHOLDER_KB_IDS = {"all", "default", "*"}

    def __init__(
        self,
        repository: RuntimeRepository,
        registry: ToolRegistry,
        approval_service: ApprovalService,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._approval_service = approval_service

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionOutcome:
        request = await self._hydrate_request_arguments(request)
        tool = await self._repository.get_tool_definition(request.tool_name)
        if tool is None:
            raise RuntimeError(f"tool not registered: {request.tool_name}")

        policy = await self._repository.get_tenant_policy(request.tenant_id)
        decision = evaluate_tool_policy(policy, tool)
        if not decision.allowed:
            raise RuntimeError(f"tool not allowed: {request.tool_name}")

        if decision.requires_approval:
            invocation = ToolInvocationRecord(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                agent_id=request.agent_id,
                tool_name=request.tool_name,
                arguments=request.arguments,
                status=ToolInvocationStatus.WAITING_FOR_APPROVAL,
            )
            await self._repository.create_tool_invocation(invocation)
            approval = await self._approval_service.request_tool_approval(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                agent_id=request.agent_id,
                tool_name=request.tool_name,
                reason=f"approval required for tool: {request.tool_name}",
            )
            return ToolExecutionOutcome(
                invocation_id=invocation.invocation_id,
                status=ToolInvocationStatus.WAITING_FOR_APPROVAL,
                requires_approval=True,
                approval_id=approval.approval_id,
            )

        executor = self._registry.get(request.tool_name)
        try:
            result = await executor.execute(request)
        except Exception as exc:
            invocation = ToolInvocationRecord(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                agent_id=request.agent_id,
                tool_name=request.tool_name,
                arguments=request.arguments,
                status=ToolInvocationStatus.FAILED,
                error=str(exc),
            )
            await self._repository.create_tool_invocation(invocation)
            raise

        invocation = ToolInvocationRecord(
            tenant_id=request.tenant_id,
            run_id=request.run_id,
            agent_id=request.agent_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            status=ToolInvocationStatus.COMPLETED,
            result=result.output,
        )
        await self._repository.create_tool_invocation(invocation)
        return ToolExecutionOutcome(
            invocation_id=invocation.invocation_id,
            status=ToolInvocationStatus.COMPLETED,
            result=result.output,
            requires_approval=False,
        )

    async def _hydrate_request_arguments(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        if request.tool_name != "rag_search":
            return request
        explicit_kb_ids = self._normalize_explicit_kb_ids(request.arguments.get("kb_ids"))
        if explicit_kb_ids:
            return request.model_copy(update={"arguments": {**request.arguments, "kb_ids": explicit_kb_ids}})
        if request.arguments.get("kb_ids") is not None:
            request = request.model_copy(update={"arguments": self._drop_kb_ids_argument(request.arguments)})

        agent = await self._repository.get_agent(request.agent_id)
        if agent is None:
            return request

        kb_ids = self._extract_selected_kb_ids(agent.observations)
        if not kb_ids:
            return request

        return request.model_copy(update={"arguments": {**request.arguments, "kb_ids": kb_ids}})

    def _extract_selected_kb_ids(self, observations: list[str]) -> list[str]:
        for observation in observations:
            match = re.search(
                r"Selected knowledge bases for retrieval:\s*(?P<kb_ids>.+?)\.\s*Use these kb_ids when calling rag_search\.",
                observation,
            )
            if match is None:
                continue

            raw_kb_ids = match.group("kb_ids")
            kb_ids = [item.strip() for item in raw_kb_ids.split(",") if item.strip()]
            if kb_ids:
                return kb_ids
        return []

    @classmethod
    def _normalize_explicit_kb_ids(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            kb_id = item.strip()
            if not kb_id:
                continue
            if kb_id.lower() in cls._PLACEHOLDER_KB_IDS:
                return []
            normalized.append(kb_id)
        return normalized

    @staticmethod
    def _drop_kb_ids_argument(arguments: dict[str, object]) -> dict[str, object]:
        sanitized = dict(arguments)
        sanitized.pop("kb_ids", None)
        return sanitized

    async def resume_approved_invocation(self, invocation_id: str) -> ToolExecutionOutcome:
        invocation = await self._repository.get_tool_invocation(invocation_id)
        if invocation is None:
            raise RuntimeError(f"tool invocation not found: {invocation_id}")

        if invocation.status == ToolInvocationStatus.COMPLETED:
            return ToolExecutionOutcome(
                invocation_id=invocation.invocation_id,
                status=invocation.status,
                result=invocation.result,
                requires_approval=False,
            )
        if invocation.status != ToolInvocationStatus.WAITING_FOR_APPROVAL:
            raise RuntimeError(
                f"tool invocation is not resumable from status={invocation.status.value}: {invocation_id}"
            )

        executor = self._registry.get(invocation.tool_name)
        request = ToolExecutionRequest(
            tenant_id=invocation.tenant_id,
            run_id=invocation.run_id,
            agent_id=invocation.agent_id,
            tool_name=invocation.tool_name,
            arguments=invocation.arguments,
        )
        try:
            result = await executor.execute(request)
        except Exception as exc:
            await self._repository.update_tool_invocation(
                invocation.invocation_id,
                status=ToolInvocationStatus.FAILED,
                error=str(exc),
            )
            raise

        await self._repository.update_tool_invocation(
            invocation.invocation_id,
            status=ToolInvocationStatus.COMPLETED,
            result=result.output,
            error=None,
        )
        return ToolExecutionOutcome(
            invocation_id=invocation.invocation_id,
            status=ToolInvocationStatus.COMPLETED,
            result=result.output,
            requires_approval=False,
        )
