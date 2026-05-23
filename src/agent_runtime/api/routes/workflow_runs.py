from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from agent_runtime.api.schemas import (
    WorkflowRunObservationDetailResponse,
    WorkflowRunObservationListItemResponse,
    WorkflowRunObservationListResponse,
)
from agent_runtime.domain.enums import RunStatus
from agent_runtime.workflows.observability import (
    WorkflowRunObservationFilter,
    WorkflowRunObservationNotFoundError,
)

router = APIRouter(prefix="/v1/workflow-runs", tags=["workflow-runs"])


def _parse_tenant_id(tenant_id: str | None) -> str:
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


def _parse_limit(limit: str | None) -> int | None:
    if limit is None:
        return None
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100") from exc
    if parsed < 1 or parsed > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return parsed


def _parse_template_version(template_version: str | None) -> int | None:
    if template_version is None:
        return None
    try:
        parsed = int(template_version)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="template_version must be a positive integer") from exc
    if parsed < 1:
        raise HTTPException(status_code=400, detail="template_version must be a positive integer")
    return parsed


def _parse_status(status: str | None) -> RunStatus | None:
    if status is None:
        return None
    try:
        return RunStatus(status)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "status must be one of: created, running, waiting_for_approval, "
                "paused, failed, completed, cancelled"
            ),
        ) from exc


def _parse_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a timezone-aware ISO 8601 datetime",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a timezone-aware ISO 8601 datetime",
        )
    return parsed.astimezone(UTC)


def _serialize_list_item(item: object) -> WorkflowRunObservationListItemResponse:
    if hasattr(item, "model_dump"):
        item = item.model_dump()
    return WorkflowRunObservationListItemResponse.model_validate(item)


@router.get("", response_model=WorkflowRunObservationListResponse)
async def list_workflow_runs(
    request: Request,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    template_version: str | None = None,
    status: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    cursor: str | None = None,
    limit: str | None = None,
) -> WorkflowRunObservationListResponse:
    filters = WorkflowRunObservationFilter(
        tenant_id=_parse_tenant_id(tenant_id),
        workflow_id=workflow_id,
        template_version=_parse_template_version(template_version),
        status=_parse_status(status),
        created_after=_parse_datetime(created_after, "created_after"),
        created_before=_parse_datetime(created_before, "created_before"),
        cursor=cursor,
        limit=_parse_limit(limit) or WorkflowRunObservationFilter.model_fields["limit"].default,
    )
    try:
        result = await request.app.state.workflow_observability_service.list_workflow_runs(filters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkflowRunObservationListResponse(
        items=[_serialize_list_item(item) for item in result["items"]],
        next_cursor=result["next_cursor"],
    )


@router.get("/{run_id}", response_model=WorkflowRunObservationDetailResponse)
async def get_workflow_run_detail(
    request: Request,
    run_id: str,
    tenant_id: str | None = None,
) -> WorkflowRunObservationDetailResponse:
    try:
        detail = await request.app.state.workflow_observability_service.get_workflow_run_detail(
            tenant_id=_parse_tenant_id(tenant_id),
            run_id=run_id,
        )
    except WorkflowRunObservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkflowRunObservationDetailResponse.model_validate(detail)
