from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    payload = request.app.state.metrics_sink.render_prometheus_text()
    return Response(
        content=payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
