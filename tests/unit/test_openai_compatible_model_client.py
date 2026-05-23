from __future__ import annotations

import json

import httpx
import pytest

from agent_runtime.domain.enums import AgentRole, DecisionKind
from agent_runtime.models.base import ModelTurnInput


def _assert_openai_compatible_request(request: httpx.Request) -> dict[str, object]:
    assert request.method == "POST"
    assert request.url.path.endswith("/chat/completions")

    payload = json.loads(request.content.decode("utf-8"))
    assert payload["model"] == "deepseek-chat"
    return payload


@pytest.mark.asyncio
async def test_openai_compatible_client_maps_finish_response_to_model_decision() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "final answer",
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        decision = await client.complete(
            ModelTurnInput(
                run_id="run-1",
                agent_id="agent-1",
                agent_role=AgentRole.SUPERVISOR,
                objective="answer",
                observations=["hello"],
            )
        )

    assert decision.kind == DecisionKind.FINISH
    assert decision.final_output == "final answer"


@pytest.mark.asyncio
async def test_openai_compatible_client_maps_tool_call_response() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "id": "chatcmpl-123",
                        "type": "chat.completion",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc123",
                                    "type": "function",
                                    "function": {
                                        "name": "rag_search",
                                        "arguments": "{\"kb_ids\": [\"kb-1\"], \"query\": \"hello\"}",
                                    }
                                }
                            ],
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        decision = await client.complete(
            ModelTurnInput(
                run_id="run-2",
                agent_id="agent-2",
                agent_role=AgentRole.SUPERVISOR,
                objective="search",
                observations=[],
            )
        )

    assert decision.kind == DecisionKind.CALL_TOOL
    assert decision.tool_name == "rag_search"
    assert decision.tool_arguments == {"kb_ids": ["kb-1"], "query": "hello"}


@pytest.mark.asyncio
async def test_openai_compatible_client_raises_runtime_error_on_bad_response() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(500, json={"error": {"message": "provider failed"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        with pytest.raises(RuntimeError, match="provider failed"):
            await client.complete(
                ModelTurnInput(
                    run_id="run-3",
                    agent_id="agent-3",
                    agent_role=AgentRole.SUPERVISOR,
                    objective="fail",
                    observations=[],
                )
            )


@pytest.mark.asyncio
async def test_openai_compatible_client_raises_runtime_error_on_non_object_error_body() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(500, json=["bad"])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        with pytest.raises(RuntimeError):
            await client.complete(
                ModelTurnInput(
                    run_id="run-3b",
                    agent_id="agent-3b",
                    agent_role=AgentRole.SUPERVISOR,
                    objective="fail",
                    observations=[],
                )
            )


@pytest.mark.asyncio
async def test_openai_compatible_client_raises_runtime_error_on_malformed_success_body() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(200, text="not json")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        with pytest.raises(RuntimeError, match="valid JSON"):
            await client.complete(
                ModelTurnInput(
                    run_id="run-4",
                    agent_id="agent-4",
                    agent_role=AgentRole.SUPERVISOR,
                    objective="answer",
                    observations=[],
                )
            )


@pytest.mark.asyncio
async def test_openai_compatible_client_raises_runtime_error_on_invalid_tool_arguments_json() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "rag_search",
                                        "arguments": "{not valid json}",
                                    }
                                }
                            ],
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        with pytest.raises(RuntimeError, match="malformed tool call"):
            await client.complete(
                ModelTurnInput(
                    run_id="run-5",
                    agent_id="agent-5",
                    agent_role=AgentRole.SUPERVISOR,
                    objective="search",
                    observations=[],
                )
            )


@pytest.mark.asyncio
async def test_openai_compatible_client_raises_runtime_error_on_non_object_tool_arguments() -> None:
    from agent_runtime.models.openai_compatible import OpenAICompatibleModelClient

    def handler(request: httpx.Request) -> httpx.Response:
        _assert_openai_compatible_request(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "rag_search",
                                        "arguments": "[1, 2, 3]",
                                    }
                                }
                            ],
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as http_client:
        client = OpenAICompatibleModelClient(
            http_client=http_client,
            model_name="deepseek-chat",
        )
        with pytest.raises(RuntimeError, match="tool arguments"):
            await client.complete(
                ModelTurnInput(
                    run_id="run-6",
                    agent_id="agent-6",
                    agent_role=AgentRole.SUPERVISOR,
                    objective="search",
                    observations=[],
                )
            )
