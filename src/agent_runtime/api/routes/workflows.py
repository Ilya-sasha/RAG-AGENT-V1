from fastapi import APIRouter, HTTPException, Request, Response, status

from agent_runtime.api.schemas import (
    WorkflowArchiveRequest,
    WorkflowCreateRequest,
    WorkflowDetailResponse,
    WorkflowLaunchRequest,
    WorkflowLaunchResponse,
    WorkflowListItemResponse,
    WorkflowListResponse,
    WorkflowPublishRequest,
    WorkflowResponse,
    WorkflowVersionCreateRequest,
    WorkflowVersionResponse,
    WorkflowVersionSummaryResponse,
    WorkflowVersionUpdateRequest,
)
from agent_runtime.workflows.service import (
    WorkflowTemplateConflictError,
    WorkflowTemplateLaunchGuardrailError,
    WorkflowTemplateNotFoundError,
    WorkflowTemplateValidationError,
)

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


def _serialize_workflow(template) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=template.template_id,
        tenant_id=template.tenant_id,
        name=template.name,
        description=template.description,
        status=template.status,
        latest_version=template.latest_version,
        latest_published_version=template.latest_published_version,
        archived_at=template.archived_at,
    )


def _serialize_workflow_list_item(item) -> WorkflowListItemResponse:
    return WorkflowListItemResponse.model_validate(item)


def _serialize_workflow_version(version) -> WorkflowVersionResponse:
    return WorkflowVersionResponse(
        version=version.version,
        definition=version.definition,
        input_schema=version.input_schema,
        source_version=version.source_version,
        is_published=version.is_published,
        created_by=version.created_by,
    )


def _raise_workflow_http_error(exc: Exception) -> None:
    if isinstance(exc, WorkflowTemplateNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, WorkflowTemplateConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, WorkflowTemplateValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _parse_workflow_list_limit(limit: str | None) -> int | None:
    if limit is None:
        return None
    try:
        return int(limit)
    except (TypeError, ValueError) as exc:
        raise WorkflowTemplateValidationError("limit must be between 1 and 100") from exc


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    request: Request,
    payload: WorkflowCreateRequest,
) -> WorkflowResponse:
    try:
        workflow = await request.app.state.workflow_service.create_template(
            template_id=payload.workflow_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            description=payload.description,
            definition=payload.definition,
            input_schema=payload.input_schema,
            created_by=payload.created_by,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return _serialize_workflow(workflow)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    request: Request,
    tenant_id: str | None = None,
    workflow_id_prefix: str | None = None,
    name_query: str | None = None,
    cursor: str | None = None,
    limit: str | None = None,
) -> WorkflowListResponse:
    try:
        if tenant_id is None or not tenant_id.strip():
            raise WorkflowTemplateValidationError("tenant_id is required")
        workflows = await request.app.state.workflow_service.list_workflows(
            tenant_id=tenant_id,
            workflow_id_prefix=workflow_id_prefix,
            name_query=name_query,
            limit=_parse_workflow_list_limit(limit),
            cursor=cursor,
        )
    except WorkflowTemplateValidationError as exc:
        _raise_workflow_http_error(exc)
    return WorkflowListResponse(
        items=[_serialize_workflow_list_item(item) for item in workflows["items"]],
        next_cursor=workflows["next_cursor"],
    )


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow_detail(
    request: Request,
    workflow_id: str,
    tenant_id: str,
) -> WorkflowDetailResponse:
    try:
        detail = await request.app.state.workflow_service.get_template_detail(tenant_id, workflow_id)
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return WorkflowDetailResponse(
        **_serialize_workflow(detail["template"]).model_dump(),
        created_at=detail["template"].created_at,
        updated_at=detail["template"].updated_at,
        latest_draft=(
            _serialize_workflow_version(detail["latest_draft"])
            if detail["latest_draft"] is not None
            else None
        ),
        latest_published=(
            _serialize_workflow_version(detail["latest_published"])
            if detail["latest_published"] is not None
            else None
        ),
        version_summaries=[
            WorkflowVersionSummaryResponse.model_validate(item) for item in detail["version_summaries"]
        ],
    )


@router.post("/{workflow_id}/versions", response_model=WorkflowVersionResponse, status_code=201)
async def create_workflow_version(
    request: Request,
    workflow_id: str,
    payload: WorkflowVersionCreateRequest,
) -> WorkflowVersionResponse:
    try:
        version = await request.app.state.workflow_service.create_template_version_draft(
            tenant_id=payload.tenant_id,
            template_id=workflow_id,
            created_by=payload.created_by,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return _serialize_workflow_version(version)


@router.put("/{workflow_id}/versions/{version}", response_model=WorkflowVersionResponse)
async def update_workflow_version(
    request: Request,
    workflow_id: str,
    version: int,
    payload: WorkflowVersionUpdateRequest,
) -> WorkflowVersionResponse:
    try:
        updated_version = await request.app.state.workflow_service.replace_template_version_draft(
            tenant_id=payload.tenant_id,
            template_id=workflow_id,
            version=version,
            definition=payload.definition,
            input_schema=payload.input_schema,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return _serialize_workflow_version(updated_version)


@router.delete("/{workflow_id}/versions/{version}", status_code=204)
async def delete_workflow_version(
    request: Request,
    workflow_id: str,
    version: int,
    tenant_id: str,
) -> Response:
    try:
        await request.app.state.workflow_service.delete_template_version(
            tenant_id=tenant_id,
            template_id=workflow_id,
            version=version,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/versions/{version}/publish", response_model=WorkflowResponse)
async def publish_workflow_version(
    request: Request,
    workflow_id: str,
    version: int,
    payload: WorkflowPublishRequest,
) -> WorkflowResponse:
    try:
        workflow = await request.app.state.workflow_service.publish_template_version(
            tenant_id=payload.tenant_id,
            template_id=workflow_id,
            version=version,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return _serialize_workflow(workflow)


@router.post("/{workflow_id}/launch", response_model=WorkflowLaunchResponse, status_code=201)
async def launch_workflow(
    request: Request,
    workflow_id: str,
    payload: WorkflowLaunchRequest,
) -> WorkflowLaunchResponse:
    try:
        run, workflow_metadata = await request.app.state.workflow_service.launch_template(
            tenant_id=payload.tenant_id,
            template_id=workflow_id,
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
    return WorkflowLaunchResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
        workflow={
            "workflow_id": workflow_metadata["template_id"],
            "version": workflow_metadata["version"],
            "name": workflow_metadata["name"],
        },
    )


@router.post("/{workflow_id}/archive", response_model=WorkflowResponse)
async def archive_workflow(
    request: Request,
    workflow_id: str,
    payload: WorkflowArchiveRequest,
) -> WorkflowResponse:
    try:
        workflow = await request.app.state.workflow_service.archive_template(
            tenant_id=payload.tenant_id,
            template_id=workflow_id,
        )
    except (
        WorkflowTemplateNotFoundError,
        WorkflowTemplateConflictError,
        WorkflowTemplateValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)
    return _serialize_workflow(workflow)
