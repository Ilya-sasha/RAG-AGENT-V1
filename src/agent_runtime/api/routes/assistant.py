from fastapi import APIRouter, HTTPException, Request

from agent_runtime.assistant.service import (
    AssistantSessionNotFoundError,
    AssistantValidationError,
)
from agent_runtime.api.schemas import (
    AssistantActivityResponse,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantMessageResponse,
    AssistantSessionCreateRequest,
    AssistantSessionResponse,
    AssistantTaskCreateRequest,
    AssistantTaskResponse,
)
from agent_runtime.workflows.service import (
    WorkflowTemplateLaunchGuardrailError,
    WorkflowTemplateNotFoundError,
    WorkflowTemplateValidationError,
)

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


def _serialize_session(session) -> AssistantSessionResponse:
    return AssistantSessionResponse.model_validate(session.model_dump())


def _serialize_message(message) -> AssistantMessageResponse:
    return AssistantMessageResponse.model_validate(message.model_dump())


def _raise_assistant_error(exc: Exception) -> None:
    if isinstance(exc, AssistantSessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, AssistantValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, WorkflowTemplateNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, WorkflowTemplateLaunchGuardrailError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, WorkflowTemplateValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.post("/sessions", response_model=AssistantSessionResponse, status_code=201)
async def create_session(
    request: Request,
    payload: AssistantSessionCreateRequest,
) -> AssistantSessionResponse:
    session = await request.app.state.assistant_service.create_session(
        tenant_id=payload.tenant_id,
        mode=payload.mode,
        title=payload.title,
    )
    return _serialize_session(session)


@router.get("/sessions", response_model=list[AssistantSessionResponse])
async def list_sessions(request: Request, tenant_id: str) -> list[AssistantSessionResponse]:
    sessions = await request.app.state.assistant_service.list_sessions(tenant_id=tenant_id)
    return [_serialize_session(session) for session in sessions]


@router.get("/sessions/{session_id}/messages", response_model=list[AssistantMessageResponse])
async def list_messages(
    request: Request,
    session_id: str,
    tenant_id: str,
) -> list[AssistantMessageResponse]:
    try:
        messages = await request.app.state.assistant_service.list_messages(
            tenant_id=tenant_id,
            session_id=session_id,
        )
    except Exception as exc:
        _raise_assistant_error(exc)
    return [_serialize_message(message) for message in messages]


@router.post("/sessions/{session_id}/chat", response_model=AssistantChatResponse)
async def chat(
    request: Request,
    session_id: str,
    payload: AssistantChatRequest,
) -> AssistantChatResponse:
    try:
        result = await request.app.state.assistant_service.send_chat_message(
            tenant_id=payload.tenant_id,
            session_id=session_id,
            content=payload.content,
            knowledge_base_ids=payload.knowledge_base_ids,
        )
    except Exception as exc:
        _raise_assistant_error(exc)
    return AssistantChatResponse(
        user_message=_serialize_message(result.user_message),
        assistant_message=_serialize_message(result.assistant_message),
        run_id=result.run_id,
        status=result.status,
    )


@router.post("/sessions/{session_id}/tasks", response_model=AssistantTaskResponse, status_code=201)
async def create_task(
    request: Request,
    session_id: str,
    payload: AssistantTaskCreateRequest,
) -> AssistantTaskResponse:
    try:
        result = await request.app.state.assistant_service.create_task(
            tenant_id=payload.tenant_id,
            session_id=session_id,
            objective=payload.objective,
            workflow_id=payload.workflow_id,
            version=payload.version,
            launch_input=payload.launch_input,
        )
    except Exception as exc:
        _raise_assistant_error(exc)
    return AssistantTaskResponse(
        request_message=_serialize_message(result.request_message),
        run_id=result.run_id,
    )


@router.get("/sessions/{session_id}/activity", response_model=AssistantActivityResponse)
async def get_activity(
    request: Request,
    session_id: str,
    tenant_id: str,
) -> AssistantActivityResponse:
    try:
        activity = await request.app.state.assistant_service.get_activity(
            tenant_id=tenant_id,
            session_id=session_id,
        )
    except Exception as exc:
        _raise_assistant_error(exc)
    return AssistantActivityResponse.model_validate(activity)
