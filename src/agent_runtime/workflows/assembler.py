from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AssembledTemplateLaunch:
    objective: str
    default_kb_ids: list[str]
    effective_allowed_tools: list[str]
    effective_approval_required_tools: list[str]
    workflow_policy: dict[str, Any]


def assemble_template_launch(
    *,
    tenant_id: str,
    template_id: str,
    template_name: str,
    version: int,
    definition: dict[str, Any],
    launch_input: dict[str, Any],
    tenant_allowed_tools: list[str],
    tenant_approval_required_tools: list[str],
    existing_kb_ids: list[str],
) -> AssembledTemplateLaunch:
    del tenant_id, template_id, template_name, version

    objective = definition["entrypoint"]["objective_template"].format_map(launch_input)
    kb_ids = list(definition.get("knowledge", {}).get("default_kb_ids", []))
    for kb_id in kb_ids:
        if kb_id not in existing_kb_ids:
            raise ValueError(f"unknown knowledge base: {kb_id}")

    allowed = sorted(set(tenant_allowed_tools).intersection(definition["tools"]["allowed_tools"]))
    if not allowed:
        raise ValueError("effective allowed tool policy is empty")

    approval_required = sorted(
        set(tenant_approval_required_tools).union(definition["tools"]["approval_required_tools"])
    )
    return AssembledTemplateLaunch(
        objective=objective,
        default_kb_ids=kb_ids,
        effective_allowed_tools=allowed,
        effective_approval_required_tools=approval_required,
        workflow_policy={
            "allowed_tools": allowed,
            "approval_required_tools": approval_required,
            "default_kb_ids": kb_ids,
        },
    )
