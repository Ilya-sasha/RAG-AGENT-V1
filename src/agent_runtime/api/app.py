import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from agent_runtime.assistant.repository import AssistantRepository
from agent_runtime.assistant.service import AssistantService
from agent_runtime.api.routes.admin import build_router as build_admin_router
from agent_runtime.api.routes.assistant import router as assistant_router
from agent_runtime.api.routes.assistant_ui import build_router as build_assistant_ui_router
from agent_runtime.api.routes.approvals import router as approvals_router
from agent_runtime.api.routes.knowledge_bases import router as knowledge_bases_router
from agent_runtime.api.routes.metrics import router as metrics_router
from agent_runtime.api.routes.runs import router as runs_router
from agent_runtime.api.routes.tenants import router as tenants_router
from agent_runtime.api.routes.tools import router as tools_router
from agent_runtime.api.routes.workflows import router as workflows_router
from agent_runtime.api.routes.workflow_runs import router as workflow_runs_router
from agent_runtime.api.routes.workflow_templates import router as workflow_templates_router
from agent_runtime.domain.models import ToolDefinitionRecord
from agent_runtime.knowledge.chunking import StructureFirstChunkingStrategy
from agent_runtime.knowledge.embedding import SubprocessEmbeddingProvider
from agent_runtime.knowledge.index import LocalPersistentVectorIndexProvider
from agent_runtime.knowledge.providers import EmbeddingProvider, VectorIndexProvider
from agent_runtime.knowledge.repository import KnowledgeRepository
from agent_runtime.knowledge.service import KnowledgeService
from agent_runtime.models.base import ModelClient
from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient
from agent_runtime.models.scripted import ScriptedModelClient
from agent_runtime.observability.context import bind_request_context, reset_request_context
from agent_runtime.observability.logging import emit_structured_log
from agent_runtime.observability.metrics import PrometheusMetricsSink
from agent_runtime.approvals.service import ApprovalService
from agent_runtime.retrieval.service import RetrievalService
from agent_runtime.runtime.services import RunService
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.event_stream import EventStreamHub
from agent_runtime.state.repositories import RuntimeRepository
from agent_runtime.testing.faults import FaultInjector, NoopFaultInjector
from agent_runtime.tools.gateway import ToolGateway
from agent_runtime.tools.rag_search import RagSearchToolExecutor
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflows.repository import WorkflowRepository
from agent_runtime.workflows.observability import WorkflowObservabilityService
from agent_runtime.workflows.service import WorkflowService


DEFAULT_DB_URL = "sqlite+aiosqlite:///./runtime.db"
DEFAULT_EMBEDDING_MODEL_ROOT = (
    r"C:\models\embedding_models\iic\nlp_gte_sentence-embedding_chinese-base"
)
STARTUP_RUN_RECOVERY_GRACE_SECONDS = 0.5
DEFAULT_RESUME_ACTIVE_RUNS_ON_STARTUP = False
ADMIN_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "admin"
ASSISTANT_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "assistant"


def _resolve_metrics_route_label(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return request.url.path


def _resolve_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(
    *,
    db_url: str | None = None,
    model_client: ModelClient | None = None,
    tool_registry: ToolRegistry | None = None,
    fault_injector: FaultInjector | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_index_provider: VectorIndexProvider | None = None,
    resume_active_runs_on_startup: bool | None = None,
) -> FastAPI:
    resolved_db_url = db_url if db_url is not None else os.getenv("AGENT_RUNTIME_DB_URL", DEFAULT_DB_URL)
    embedding_model_root = os.getenv(
        "AGENT_RUNTIME_EMBEDDING_MODEL_ROOT",
        DEFAULT_EMBEDDING_MODEL_ROOT,
    )
    compatible_base_url = os.getenv("AGENT_RUNTIME_MODEL_BASE_URL","https://api.deepseek.com")
    compatible_api_key = os.getenv("AGENT_RUNTIME_MODEL_API_KEY")
    compatible_model_name = os.getenv("AGENT_RUNTIME_MODEL_NAME","deepseek-v4-flash")
    compatible_timeout_seconds = float(os.getenv("AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS", "60"))
    resolved_resume_active_runs_on_startup = (
        resume_active_runs_on_startup
        if resume_active_runs_on_startup is not None
        else _resolve_bool_env(
            "AGENT_RUNTIME_RESUME_ACTIVE_RUNS_ON_STARTUP",
            DEFAULT_RESUME_ACTIVE_RUNS_ON_STARTUP,
        )
    )
    rag_search_tool_definition = ToolDefinitionRecord(
        tool_name="rag_search",
        description="Searches tenant knowledge-base chunks by semantic similarity.",
        input_schema={
            "type": "object",
            "properties": {
                "kb_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1},
                "include_compiled_context": {"type": "boolean"},
            },
            "required": ["kb_ids", "query"],
        },
        requires_approval=False,
    )
    session_factory = build_session_factory(resolved_db_url)
    repository = RuntimeRepository(session_factory)
    workflow_repository = WorkflowRepository(session_factory)
    knowledge_repository = KnowledgeRepository(session_factory)
    assistant_repository = AssistantRepository(session_factory)
    event_hub = EventStreamHub(repository.list_events)
    approval_service = ApprovalService(repository)
    metrics_sink = PrometheusMetricsSink()
    runtime_logger = logging.getLogger("agent_runtime")
    runtime_fault_injector = fault_injector or NoopFaultInjector()
    registry = tool_registry or ToolRegistry()
    tool_gateway = ToolGateway(repository, registry, approval_service)
    runtime_embedding_provider = embedding_provider or SubprocessEmbeddingProvider(embedding_model_root)
    runtime_vector_index_provider = vector_index_provider or LocalPersistentVectorIndexProvider(knowledge_repository)
    chunking_strategy = StructureFirstChunkingStrategy()
    runtime_model_client = model_client
    owned_model_http_client: httpx.AsyncClient | None = None
    if runtime_model_client is None and compatible_base_url and compatible_model_name:
        headers: dict[str, str] = {}
        if compatible_api_key:
            headers["Authorization"] = f"Bearer {compatible_api_key}"
        owned_model_http_client = httpx.AsyncClient(
            base_url=compatible_base_url.rstrip("/"),
            headers=headers,
            timeout=compatible_timeout_seconds,
        )
        runtime_model_client = OpenAICompatibleModelClient(
            http_client=owned_model_http_client,
            model_name=compatible_model_name,
        )
    if runtime_model_client is None:
        runtime_model_client = ScriptedModelClient({"supervisor": []})
    knowledge_service = KnowledgeService(
        knowledge_repository,
        runtime_embedding_provider,
        runtime_vector_index_provider,
        chunking_strategy,
        metrics_sink=metrics_sink,
    )
    retrieval_service = RetrievalService(
        runtime_embedding_provider,
        runtime_vector_index_provider,
        knowledge_repository=knowledge_repository,
        metrics_sink=metrics_sink,
    )

    try:
        registry.get("rag_search")
    except RuntimeError:
        registry.register("rag_search", RagSearchToolExecutor(retrieval_service))

    init_lock = asyncio.Lock()

    async def ensure_initialized() -> None:
        if getattr(app.state, "db_initialized", False):
            return

        async with init_lock:
            if not getattr(app.state, "db_initialized", False):
                await init_db(session_factory)
                await repository.upsert_tool_definition(rag_search_tool_definition)
                app.state.db_initialized = True

    async def shutdown_runtime() -> None:
        await app.state.run_service.shutdown()
        if app.state.owned_model_http_client is not None:
            await app.state.owned_model_http_client.aclose()
        await dispose_session_factory(session_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await ensure_initialized()
        if resolved_resume_active_runs_on_startup:
            recovery_tasks = await app.state.run_service.resume_active_runs_in_background()
            if recovery_tasks:
                await asyncio.wait(recovery_tasks, timeout=STARTUP_RUN_RECOVERY_GRACE_SECONDS)
        try:
            yield
        finally:
            await shutdown_runtime()

    app = FastAPI(title="Agent Runtime", version="0.1.0", lifespan=lifespan)

    app.state.run_service = RunService(
        repository,
        runtime_model_client,
        event_hub,
        tool_gateway=tool_gateway,
        workflow_repository=workflow_repository,
        metrics_sink=metrics_sink,
        runtime_logger=runtime_logger,
        fault_injector=runtime_fault_injector,
    )
    app.state.workflow_service = WorkflowService(
        workflow_repository=workflow_repository,
        runtime_repository=repository,
        knowledge_repository=knowledge_repository,
        run_service=app.state.run_service,
    )
    app.state.assistant_service = AssistantService(
        assistant_repository=assistant_repository,
        run_service=app.state.run_service,
        workflow_service=app.state.workflow_service,
        runtime_repository=repository,
    )
    app.state.workflow_observability_service = WorkflowObservabilityService(
        workflow_repository=workflow_repository,
        runtime_repository=repository,
    )
    app.state.db_initialized = False
    app.state.ensure_initialized = ensure_initialized
    app.state.session_factory = session_factory
    app.state.owned_model_http_client = owned_model_http_client
    app.state.shutdown_runtime = shutdown_runtime
    app.state.metrics_sink = metrics_sink
    app.state.runtime_logger = runtime_logger
    app.state.knowledge_repository = knowledge_repository
    app.state.embedding_provider = runtime_embedding_provider
    app.state.vector_index_provider = runtime_vector_index_provider
    app.state.chunking_strategy = chunking_strategy
    app.state.knowledge_service = knowledge_service
    app.state.retrieval_service = retrieval_service

    @app.middleware("http")
    async def initialize_database(request: Request, call_next):
        await request.app.state.ensure_initialized()
        return await call_next(request)

    @app.middleware("http")
    async def instrument_requests(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        token = bind_request_context(request_id=request_id)
        started = time.perf_counter()
        response = None
        try:
            emit_structured_log(
                request.app.state.runtime_logger,
                "request started",
                component="api",
                context={"request_id": request_id},
                fields={"method": request.method, "path": request.url.path},
            )
            response = await call_next(request)
            return response
        finally:
            duration = time.perf_counter() - started
            status_code = response.status_code if response is not None else 500
            route_label = _resolve_metrics_route_label(request)
            request.app.state.metrics_sink.record_http_request(
                method=request.method,
                route=route_label,
                status_code=status_code,
                duration_seconds=duration,
            )
            emit_structured_log(
                request.app.state.runtime_logger,
                "request completed",
                component="api",
                context={"request_id": request_id},
                fields={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            reset_request_context(token)

    @app.get("/health")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/admin/assets", StaticFiles(directory=ADMIN_ASSETS_DIR), name="admin-assets")
    app.include_router(build_admin_router(ADMIN_ASSETS_DIR))
    app.mount("/assistant/assets", StaticFiles(directory=ASSISTANT_ASSETS_DIR), name="assistant-assets")
    app.include_router(build_assistant_ui_router(ASSISTANT_ASSETS_DIR))
    app.include_router(metrics_router)
    app.include_router(runs_router)
    app.include_router(assistant_router)
    app.include_router(approvals_router)
    app.include_router(tools_router)
    app.include_router(tenants_router)
    app.include_router(knowledge_bases_router)
    app.include_router(workflows_router)
    app.include_router(workflow_runs_router)
    app.include_router(workflow_templates_router)
    return app
