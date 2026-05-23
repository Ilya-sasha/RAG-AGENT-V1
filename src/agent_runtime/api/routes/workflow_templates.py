from fastapi import APIRouter, HTTPException, Request, Response, status

from agent_runtime.api.schemas import (
    WorkflowTemplateArchiveRequest,
    WorkflowTemplateCreateRequest,
    WorkflowTemplateDetailResponse,
    WorkflowTemplateLaunchRequest,
    WorkflowTemplateLaunchResponse,
    WorkflowTemplatePublishRequest,
    WorkflowTemplateResponse,
    WorkflowTemplateLifecycleResponse,
    WorkflowTemplateVersionCreateRequest,
    WorkflowTemplateVersionResponse,
    WorkflowTemplateVersionSummaryResponse,
    WorkflowTemplateVersionUpdateRequest,
)
from agent_runtime.workflows.service import (
    WorkflowTemplateConflictError,
    WorkflowTemplateLaunchGuardrailError,
    WorkflowTemplateNotFoundError,
    WorkflowTemplateValidationError,
)

router = APIRouter(prefix="/v1/workflow-templates", tags=["workflow-templates"])


def _serialize_workflow_template(template) -> WorkflowTemplateResponse:
    return WorkflowTemplateResponse.model_validate(template.model_dump())


def _serialize_workflow_template_lifecycle(template) -> WorkflowTemplateLifecycleResponse:
    return WorkflowTemplateLifecycleResponse(
        template_id=template.template_id,
        tenant_id=template.tenant_id,
        name=template.name,
        description=template.description,
        status=template.status,
        latest_version=template.latest_version,
        latest_published_version=template.latest_published_version,
        archived_at=template.archived_at,
    )


def _serialize_workflow_template_version(version) -> WorkflowTemplateVersionResponse:
    return WorkflowTemplateVersionResponse(
        version=version.version,
        definition=version.definition,
        input_schema=version.input_schema,
        source_version=version.source_version,
        is_published=version.is_published,
        created_by=version.created_by,
    )


@router.post("", response_model=WorkflowTemplateResponse, status_code=201)
async def create_workflow_template(
    request: Request,
    payload: WorkflowTemplateCreateRequest,
) -> WorkflowTemplateResponse:
    try:
        template = await request.app.state.workflow_service.create_template(
            template_id=payload.template_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            description=payload.description,
            definition=payload.definition,
            input_schema=payload.input_schema,
            created_by=payload.created_by,
        )
    except WorkflowTemplateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_workflow_template(template)


@router.get("", response_model=list[WorkflowTemplateResponse])
async def list_workflow_templates(request: Request, tenant_id: str) -> list[WorkflowTemplateResponse]:
    templates = await request.app.state.workflow_service.list_templates(tenant_id)
    return [_serialize_workflow_template(item) for item in templates]


@router.get("/{template_id}", response_model=WorkflowTemplateDetailResponse)
async def get_workflow_template_detail(
    request: Request,
    template_id: str,
    tenant_id: str,
) -> WorkflowTemplateDetailResponse:
    try:
        detail = await request.app.state.workflow_service.get_template_detail(tenant_id, template_id)
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkflowTemplateDetailResponse(
        **_serialize_workflow_template_lifecycle(detail["template"]).model_dump(),
        created_at=detail["template"].created_at,
        updated_at=detail["template"].updated_at,
        latest_draft=(
            _serialize_workflow_template_version(detail["latest_draft"])
            if detail["latest_draft"] is not None
            else None
        ),
        latest_published=(
            _serialize_workflow_template_version(detail["latest_published"])
            if detail["latest_published"] is not None
            else None
        ),
        version_summaries=[
            WorkflowTemplateVersionSummaryResponse.model_validate(item)
            for item in detail["version_summaries"]
        ],
    )


@router.post("/{template_id}/versions", response_model=WorkflowTemplateVersionResponse, status_code=201)
async def create_workflow_template_version(
    request: Request,
    template_id: str,
    payload: WorkflowTemplateVersionCreateRequest,
) -> WorkflowTemplateVersionResponse:
    try:
        version = await request.app.state.workflow_service.create_template_version_draft(
            tenant_id=payload.tenant_id,
            template_id=template_id,
            created_by=payload.created_by,
        )
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowTemplateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_workflow_template_version(version)


@router.put("/{template_id}/versions/{version}", response_model=WorkflowTemplateVersionResponse)
async def update_workflow_template_version(
    request: Request,
    template_id: str,
    version: int,
    payload: WorkflowTemplateVersionUpdateRequest,
) -> WorkflowTemplateVersionResponse:
    try:
        updated_version = await request.app.state.workflow_service.replace_template_version_draft(
            tenant_id=payload.tenant_id,
            template_id=template_id,
            version=version,
            definition=payload.definition,
            input_schema=payload.input_schema,
        )
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowTemplateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_workflow_template_version(updated_version)


@router.delete("/{template_id}/versions/{version}", status_code=204)
async def delete_workflow_template_version(
    request: Request,
    template_id: str,
    version: int,
    tenant_id: str,
) -> Response:
    try:
        await request.app.state.workflow_service.delete_template_version(
            tenant_id=tenant_id,
            template_id=template_id,
            version=version,
        )
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowTemplateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{template_id}/versions/{version}/publish", response_model=WorkflowTemplateResponse)
async def publish_workflow_template_version(
    request: Request,
    template_id: str,
    version: int,
    payload: WorkflowTemplatePublishRequest,
) -> WorkflowTemplateResponse:
    try:
        template = await request.app.state.workflow_service.publish_template_version(
            tenant_id=payload.tenant_id,
            template_id=template_id,
            version=version,
        )
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_workflow_template(template)


@router.post("/{template_id}/archive", response_model=WorkflowTemplateLifecycleResponse)
async def archive_workflow_template(
    request: Request,
    template_id: str,
    payload: WorkflowTemplateArchiveRequest,
) -> WorkflowTemplateLifecycleResponse:
    try:
        template = await request.app.state.workflow_service.archive_template(
            tenant_id=payload.tenant_id,
            template_id=template_id,
        )
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_workflow_template_lifecycle(template)


@router.post("/{template_id}/launch", response_model=WorkflowTemplateLaunchResponse, status_code=201)
async def launch_workflow_template(
    request: Request,
    template_id: str,
    payload: WorkflowTemplateLaunchRequest,
) -> WorkflowTemplateLaunchResponse:
    try:
        run, workflow_metadata = await request.app.state.workflow_service.launch_template(
            tenant_id=payload.tenant_id,
            template_id=template_id,
            version=payload.version,
            launch_input=payload.input,
            metadata=payload.metadata,
        )
    except WorkflowTemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowTemplateLaunchGuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorkflowTemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkflowTemplateLaunchResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
        workflow_template=workflow_metadata,
    )
