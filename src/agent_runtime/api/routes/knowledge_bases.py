from fastapi import APIRouter, HTTPException, Request

from agent_runtime.api.schemas import (
    ActionAcceptedResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
)
from agent_runtime.domain.models import KnowledgeBaseRecord
from agent_runtime.knowledge.service import KnowledgeBaseConflictError

router = APIRouter(prefix="/internal/knowledge-bases", tags=["knowledge-bases"])


def _to_response(record: KnowledgeBaseRecord) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        kb_id=record.kb_id,
        tenant_id=record.tenant_id,
        name=record.name,
        root_path=record.root_path,
        status=record.status,
        document_count=record.document_count,
        chunk_count=record.chunk_count,
        last_error=record.last_error,
    )


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(
    request: Request,
    payload: KnowledgeBaseCreateRequest,
) -> KnowledgeBaseResponse:
    try:
        knowledge_base = await request.app.state.knowledge_service.register_knowledge_base(
            kb_id=payload.kb_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            root_path=payload.root_path,
            metadata=payload.metadata,
        )
    except KnowledgeBaseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(knowledge_base)


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    request: Request,
    tenant_id: str | None = None,
) -> list[KnowledgeBaseResponse]:
    knowledge_bases = await request.app.state.knowledge_service.list_knowledge_bases(tenant_id=tenant_id)
    return [_to_response(record) for record in knowledge_bases]


@router.get("/{kb_id}/status", response_model=KnowledgeBaseResponse)
async def get_knowledge_base_status(
    request: Request,
    kb_id: str,
    tenant_id: str | None = None,
) -> KnowledgeBaseResponse:
    try:
        knowledge_base = await request.app.state.knowledge_service.get_status(kb_id, tenant_id=tenant_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(knowledge_base)


@router.post("/{kb_id}/ingest", response_model=ActionAcceptedResponse, status_code=202)
async def ingest_knowledge_base(
    request: Request,
    kb_id: str,
    tenant_id: str | None = None,
) -> ActionAcceptedResponse:
    try:
        await request.app.state.knowledge_service.ingest(kb_id, tenant_id=tenant_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionAcceptedResponse(status="accepted")


@router.post("/{kb_id}/reindex", response_model=ActionAcceptedResponse, status_code=202)
async def reindex_knowledge_base(
    request: Request,
    kb_id: str,
    tenant_id: str | None = None,
) -> ActionAcceptedResponse:
    try:
        await request.app.state.knowledge_service.reindex(kb_id, tenant_id=tenant_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionAcceptedResponse(status="accepted")
