from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent_runtime.api.schemas import (
    ActionAcceptedResponse,
    CreateRunRequest,
    EventReplayResponse,
    RunResponse,
)

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(request: Request, payload: CreateRunRequest) -> RunResponse:
    run = await request.app.state.run_service.create_run(
        payload.tenant_id,
        payload.objective,
    )
    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(request: Request, run_id: str) -> RunResponse:
    try:
        run = await request.app.state.run_service.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(request: Request, run_id: str) -> RunResponse:
    try:
        run = await request.app.state.run_service.resume_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return RunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        objective=run.objective,
        status=run.status.value,
        result=run.result,
        error=run.error,
    )


@router.post("/{run_id}/cancel", response_model=ActionAcceptedResponse, status_code=202)
async def cancel_run(request: Request, run_id: str) -> ActionAcceptedResponse:
    try:
        await request.app.state.run_service.cancel_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionAcceptedResponse(status="accepted")


@router.get("/{run_id}/events")
async def stream_events(request: Request, run_id: str) -> StreamingResponse:
    try:
        stream = await request.app.state.run_service.stream_events(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
    )


@router.get("/{run_id}/events/replay", response_model=EventReplayResponse)
async def replay_events(request: Request, run_id: str) -> EventReplayResponse:
    try:
        events = await request.app.state.run_service.replay_events(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EventReplayResponse(events=[event.model_dump(mode="json") for event in events])
