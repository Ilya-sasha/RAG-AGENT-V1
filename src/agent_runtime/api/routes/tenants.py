from fastapi import APIRouter, HTTPException, Request

from agent_runtime.api.schemas import TenantPolicyRequest, TenantPolicyResponse
from agent_runtime.domain.models import TenantPolicyRecord

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


@router.put("/{tenant_id}/policies", response_model=TenantPolicyResponse)
async def put_tenant_policy(
    request: Request,
    tenant_id: str,
    payload: TenantPolicyRequest,
) -> TenantPolicyResponse:
    repository = request.app.state.run_service._repository
    policy = TenantPolicyRecord(
        tenant_id=tenant_id,
        allowed_tools=payload.allowed_tools,
        approval_required_tools=payload.approval_required_tools,
    )
    await repository.upsert_tenant_policy(policy)
    return TenantPolicyResponse(
        tenant_id=policy.tenant_id,
        allowed_tools=policy.allowed_tools,
        approval_required_tools=policy.approval_required_tools,
    )


@router.get("/{tenant_id}", response_model=TenantPolicyResponse)
async def get_tenant_policy(request: Request, tenant_id: str) -> TenantPolicyResponse:
    repository = request.app.state.run_service._repository
    policy = await repository.get_tenant_policy(tenant_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"tenant policy not found: {tenant_id}")
    return TenantPolicyResponse(
        tenant_id=policy.tenant_id,
        allowed_tools=policy.allowed_tools,
        approval_required_tools=policy.approval_required_tools,
    )
