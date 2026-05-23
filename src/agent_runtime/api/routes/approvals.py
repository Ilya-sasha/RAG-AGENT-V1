from fastapi import APIRouter, HTTPException, Request

from agent_runtime.api.schemas import (
    ActionAcceptedResponse,
    ApprovalActionRequest,
    ApprovalResponse,
)

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(request: Request, approval_id: str) -> ApprovalResponse:
    try:
        approval = await request.app.state.run_service.get_approval(approval_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ApprovalResponse(
        approval_id=approval.approval_id,
        tenant_id=approval.tenant_id,
        run_id=approval.run_id,
        agent_id=approval.agent_id,
        tool_name=approval.tool_name,
        reason=approval.reason,
        status=approval.status.value,
        resolution_note=approval.resolution_note,
    )


@router.post("/{approval_id}/approve", response_model=ActionAcceptedResponse)
async def approve_approval(
    request: Request,
    approval_id: str,
    payload: ApprovalActionRequest | None = None,
) -> ActionAcceptedResponse:
    try:
        await request.app.state.run_service.approve_approval(
            approval_id,
            resolution_note=payload.resolution_note if payload is not None else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ActionAcceptedResponse(status="accepted")


@router.post("/{approval_id}/reject", response_model=ActionAcceptedResponse)
async def reject_approval(
    request: Request,
    approval_id: str,
    payload: ApprovalActionRequest | None = None,
) -> ActionAcceptedResponse:
    try:
        await request.app.state.run_service.reject_approval(
            approval_id,
            resolution_note=payload.resolution_note if payload is not None else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ActionAcceptedResponse(status="accepted")
