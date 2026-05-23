import pytest

from agent_runtime.api.app import create_app
from tests.conftest import app_client_context


@pytest.mark.asyncio
async def test_assistant_workspace_page_is_served(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        response = await client.get("/assistant")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "智能助手工作台" in response.text
    assert "租户" in response.text
    assert "/assistant/assets/assistant.js" in response.text


@pytest.mark.asyncio
async def test_assistant_workspace_assets_are_served(tmp_path) -> None:
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    async with app_client_context(app) as client:
        script_response = await client.get("/assistant/assets/assistant.js")
        stylesheet_response = await client.get("/assistant/assets/assistant.css")

    assert script_response.status_code == 200
    assert "javascript" in script_response.headers["content-type"]
    assert "loadSessions" in script_response.text
    assert "clearSelectedSessionViews" in script_response.text
    assert "/v1/workflow-runs/" not in script_response.text
    assert "请选择一个会话" in script_response.text

    assert stylesheet_response.status_code == 200
    assert "text/css" in stylesheet_response.headers["content-type"]
    assert ".workspace-shell" in stylesheet_response.text
