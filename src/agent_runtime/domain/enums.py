from enum import StrEnum


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentStatus(StrEnum):
    CREATED = "created"
    READY = "ready"
    REASONING = "reasoning"
    WAITING_ON_WORKERS = "waiting_on_workers"
    WAITING_ON_TOOL = "waiting_on_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    TOOL_RUNNER = "tool-runner"


class DecisionKind(StrEnum):
    FINISH = "finish"
    DELEGATE = "delegate"
    CALL_TOOL = "call_tool"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolInvocationStatus(StrEnum):
    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    AGENT_STARTED = "agent.started"
    AGENT_REASONED = "agent.reasoned"
    AGENT_COMPLETED = "agent.completed"
    TASK_DISPATCHED = "task.dispatched"
    CHECKPOINT_CREATED = "checkpoint.created"
    TOOL_CALLED = "tool.called"
    TOOL_COMPLETED = "tool.completed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
