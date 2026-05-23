from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


def build_router(assistant_assets_dir: Path) -> APIRouter:
    router = APIRouter(tags=["assistant-ui"])
    index_path = assistant_assets_dir / "index.html"

    @router.get("/assistant", include_in_schema=False)
    async def assistant_workspace() -> FileResponse:
        return FileResponse(index_path)

    return router
