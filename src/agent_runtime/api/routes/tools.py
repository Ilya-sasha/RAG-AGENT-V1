from fastapi import APIRouter, HTTPException, Request

from agent_runtime.api.schemas import ToolDefinitionRequest, ToolDefinitionResponse
from agent_runtime.domain.models import ToolDefinitionRecord

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.post("", response_model=ToolDefinitionResponse, status_code=201)
async def register_tool(request: Request, payload: ToolDefinitionRequest) -> ToolDefinitionResponse:
    repository = request.app.state.run_service._repository
    tool = ToolDefinitionRecord(
        tool_name=payload.tool_name,
        description=payload.description,
        input_schema=payload.input_schema,
        requires_approval=payload.requires_approval,
    )
    await repository.upsert_tool_definition(tool)
    return ToolDefinitionResponse(
        tool_name=tool.tool_name,
        description=tool.description,
        input_schema=tool.input_schema,
        requires_approval=tool.requires_approval,
    )


@router.get("/{tool_name}", response_model=ToolDefinitionResponse)
async def get_tool(request: Request, tool_name: str) -> ToolDefinitionResponse:
    repository = request.app.state.run_service._repository
    tool = await repository.get_tool_definition(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool not found: {tool_name}")
    return ToolDefinitionResponse(
        tool_name=tool.tool_name,
        description=tool.description,
        input_schema=tool.input_schema,
        requires_approval=tool.requires_approval,
    )
