from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_runtime.domain.models import utc_now


class AssistantSessionRecord(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    title: str
    mode: str
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AssistantMessageRecord(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    tenant_id: str
    role: str
    content: str
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AssistantRunLinkRecord(BaseModel):
    link_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    message_id: str
    run_id: str
    launch_kind: str
    created_at: datetime = Field(default_factory=utc_now)
