from __future__ import annotations

from agent_runtime.domain.enums import AgentRole

PREDEFINED_WORKER_ROLES = {AgentRole.RESEARCHER, AgentRole.TOOL_RUNNER}


def ensure_predefined_worker(role: AgentRole) -> AgentRole:
    if role not in PREDEFINED_WORKER_ROLES:
        raise RuntimeError(f"unsupported worker role: {role}")
    return role
