import pytest
from httpx import AsyncClient

from agent_runtime.api.app import DEFAULT_DB_URL, create_app
from agent_runtime.main import app as main_app
from agent_runtime.state.db import _SESSION_FACTORY_ENGINES, dispose_session_factory
from tests.conftest import app_client_context


def test_default_embedding_model_root_points_to_concrete_model_directory() -> None:
    from agent_runtime.api.app import DEFAULT_EMBEDDING_MODEL_ROOT

    assert DEFAULT_EMBEDDING_MODEL_ROOT.endswith("iic\\nlp_gte_sentence-embedding_chinese-base")


@pytest.mark.asyncio
async def test_healthcheck_returns_ok() -> None:
    app = create_app()

    async with app_client_context(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_main_exposes_created_app() -> None:
    assert main_app.title == "Agent Runtime"
    assert main_app.version == "0.1.0"


@pytest.mark.asyncio
async def test_fixture_backed_client_runs_healthcheck(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_metrics_endpoint_exports_prometheus_text(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        health_response = await client.get("/health")
        metrics_response = await client.get("/metrics")

    assert health_response.status_code == 200
    assert metrics_response.status_code == 200
    assert "http_requests_total" in metrics_response.text
    assert 'route="/health"' in metrics_response.text


@pytest.mark.asyncio
async def test_admin_console_page_is_served(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        response = await client.get("/admin")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Agent Runtime Admin Console</title>" in response.text
    assert "/admin/assets/admin.js" in response.text
    assert "/admin/assets/admin.css" in response.text


@pytest.mark.asyncio
async def test_admin_console_assets_are_served(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        script_response = await client.get("/admin/assets/admin.js")
        stylesheet_response = await client.get("/admin/assets/admin.css")

    assert script_response.status_code == 200
    assert "javascript" in script_response.headers["content-type"]
    assert "loadOverview" in script_response.text
    assert stylesheet_response.status_code == 200
    assert "text/css" in stylesheet_response.headers["content-type"]
    assert ".hero" in stylesheet_response.text


@pytest.mark.asyncio
async def test_app_lifespan_releases_session_factory_engine() -> None:
    app = create_app()

    session_factory = app.state.session_factory
    assert session_factory in _SESSION_FACTORY_ENGINES

    async with app.router.lifespan_context(app):
        pass

    assert session_factory not in _SESSION_FACTORY_ENGINES


@pytest.mark.asyncio
async def test_create_app_uses_environment_defaults_when_arguments_omitted(monkeypatch, tmp_path) -> None:
    env_db_url = f"sqlite+aiosqlite:///{tmp_path / 'env-runtime.db'}"
    env_model_root = str(tmp_path / "embedding-models")

    monkeypatch.setenv("AGENT_RUNTIME_DB_URL", env_db_url)
    monkeypatch.setenv("AGENT_RUNTIME_EMBEDDING_MODEL_ROOT", env_model_root)

    app = create_app()
    session_factory = app.state.session_factory

    try:
        engine = _SESSION_FACTORY_ENGINES[session_factory]
        assert str(engine.url) == env_db_url
        assert app.state.embedding_provider._model_path == env_model_root
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_create_app_preserves_explicit_db_url_over_environment(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_DB_URL", "sqlite+aiosqlite:///./env-runtime.db")

    app = create_app(db_url=DEFAULT_DB_URL)
    session_factory = app.state.session_factory

    try:
        engine = _SESSION_FACTORY_ENGINES[session_factory]
        assert str(engine.url) == DEFAULT_DB_URL
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_create_app_uses_openai_compatible_model_client_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_MODEL_BASE_URL", "https://api.deepseek.local/v1")
    monkeypatch.setenv("AGENT_RUNTIME_MODEL_API_KEY", "secret-key")
    monkeypatch.setenv("AGENT_RUNTIME_MODEL_NAME", "deepseek-chat")
    monkeypatch.setenv("AGENT_RUNTIME_MODEL_TIMEOUT_SECONDS", "12.5")

    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    assert isinstance(app.state.run_service._model_client, OpenAICompatibleModelClient)
    assert app.state.owned_model_http_client is not None
    assert str(app.state.owned_model_http_client.base_url) == "https://api.deepseek.local/v1/"
    assert app.state.owned_model_http_client.headers["Authorization"] == "Bearer secret-key"
    assert app.state.owned_model_http_client.timeout.read == 12.5

    await dispose_session_factory(app.state.session_factory)


@pytest.mark.asyncio
async def test_app_lifespan_closes_owned_compatible_provider_http_client(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_MODEL_BASE_URL", "https://api.deepseek.local/v1")
    monkeypatch.setenv("AGENT_RUNTIME_MODEL_NAME", "deepseek-chat")

    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
    http_client = app.state.owned_model_http_client

    assert http_client is not None
    assert http_client.is_closed is False

    async with app.router.lifespan_context(app):
        pass

    assert http_client.is_closed is True
