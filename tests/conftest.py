from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent_runtime.api.app import create_app
from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelDecision
from agent_runtime.models.scripted import ScriptedModelClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def scripted_supervisor_client() -> ScriptedModelClient:
    return ScriptedModelClient(
        {
            "supervisor": [
                ModelDecision(
                    kind=DecisionKind.FINISH,
                    summary="done",
                    final_output="fixture result",
                )
            ]
        }
    )


@asynccontextmanager
async def app_client_context(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client


@pytest.fixture
async def api_client(
    tmp_path,
    scripted_supervisor_client: ScriptedModelClient,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        model_client=scripted_supervisor_client,
    )
    async with app_client_context(app) as client:
        yield client
