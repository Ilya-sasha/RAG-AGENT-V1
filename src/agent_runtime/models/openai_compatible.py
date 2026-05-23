from __future__ import annotations

import json
from typing import Any

import httpx

from agent_runtime.domain.enums import DecisionKind
from agent_runtime.models.base import ModelClient, ModelDecision, ModelTurnInput


class OpenAICompatibleModelClient(ModelClient):
    def __init__(self, http_client: httpx.AsyncClient, model_name: str) -> None:
        self._http_client = http_client
        self._model_name = model_name

    async def complete(self, turn: ModelTurnInput) -> ModelDecision:
        response = await self._http_client.post(
            "/chat/completions",
            json={
                "model": self._model_name,
                "messages": self._build_messages(turn),
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "rag_search",
                            "description": "Search the configured knowledge base.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "kb_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "query": {"type": "string"},
                                    "top_k": {"type": "integer"},
                                    "include_compiled_context": {"type": "boolean"},
                                },
                                "required": ["kb_ids", "query"],
                            },
                        },
                    }
                ],
            },
        )

        if response.status_code >= 400:
            raise RuntimeError(self._extract_error_detail(response))

        payload = self._parse_success_payload(response)
        message = self._extract_message(payload)

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return self._build_tool_decision(tool_calls[0])

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return ModelDecision(
                kind=DecisionKind.FINISH,
                summary="finish response",
                final_output=content,
            )

        raise RuntimeError("compatible provider returned no assistant content")

    def _build_messages(self, turn: ModelTurnInput) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": "You are an assistant running inside Agent Runtime. Use tools when needed.",
            }
        ]
        messages.extend({"role": "user", "content": observation} for observation in turn.observations)
        messages.append({"role": "user", "content": turn.objective})
        return messages

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text

        if not isinstance(payload, dict):
            return response.text

        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message

        return response.text

    def _parse_success_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("compatible provider returned a success response without valid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("compatible provider returned an invalid response payload")

        return payload

    def _extract_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    return message

        raise RuntimeError("compatible provider returned no usable assistant message")

    def _build_tool_decision(self, tool_call: Any) -> ModelDecision:
        if not isinstance(tool_call, dict):
            raise RuntimeError("compatible provider returned malformed tool call payload")

        function_call = tool_call.get("function")
        if not isinstance(function_call, dict):
            raise RuntimeError("compatible provider returned malformed tool call payload")

        tool_name = function_call.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise RuntimeError("compatible provider returned malformed tool call payload")

        arguments_raw = function_call.get("arguments", "{}")
        if not isinstance(arguments_raw, str):
            raise RuntimeError("compatible provider returned malformed tool call arguments")

        try:
            tool_arguments = json.loads(arguments_raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"compatible provider returned malformed tool call arguments for {tool_name}") from exc

        if not isinstance(tool_arguments, dict):
            raise RuntimeError(f"compatible provider returned non-object tool arguments for {tool_name}")

        return ModelDecision(
            kind=DecisionKind.CALL_TOOL,
            summary=f"call tool {tool_name}",
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )
