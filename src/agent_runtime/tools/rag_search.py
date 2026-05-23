from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StrictBool, StrictStr, ValidationError

from agent_runtime.retrieval.service import RetrievalService
from agent_runtime.tools.base import ToolExecutionRequest, ToolExecutionResult


class RagSearchArguments(BaseModel):
    kb_ids: Annotated[list[StrictStr], Field(min_length=1)]
    query: StrictStr
    top_k: Annotated[int, Field(strict=True, gt=0)] = 5
    include_compiled_context: StrictBool = False


class RagSearchToolExecutor:
    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        try:
            arguments = RagSearchArguments.model_validate(request.arguments)
        except ValidationError as exc:
            raise ValueError(f"invalid rag_search arguments: {exc}") from exc

        response = await self._retrieval_service.search(
            tenant_id=request.tenant_id,
            kb_ids=arguments.kb_ids,
            query=arguments.query,
            top_k=arguments.top_k,
            include_compiled_context=arguments.include_compiled_context,
        )
        return ToolExecutionResult(output=response.model_dump(mode="json"))
