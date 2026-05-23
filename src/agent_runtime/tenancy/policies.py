from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.domain.models import TenantPolicyRecord, ToolDefinitionRecord


@dataclass(slots=True)
class ToolPolicyDecision:
    allowed: bool
    requires_approval: bool


def evaluate_tool_policy(
    policy: TenantPolicyRecord | None,
    tool: ToolDefinitionRecord,
) -> ToolPolicyDecision:
    if policy is None:
        return ToolPolicyDecision(allowed=False, requires_approval=False)

    allowed = tool.tool_name in policy.allowed_tools
    requires_approval = tool.requires_approval or tool.tool_name in policy.approval_required_tools
    return ToolPolicyDecision(allowed=allowed, requires_approval=requires_approval)
