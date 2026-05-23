from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


def build_router(admin_assets_dir: Path) -> APIRouter:
    router = APIRouter(tags=["admin"])
    index_path = admin_assets_dir / "index.html"

    @router.get("/admin", include_in_schema=False)
    async def admin_console() -> FileResponse:
        return FileResponse(index_path)

    return router
