"""公开品牌资源：登录页在未登录时也能读取管理员上传的 Logo。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services import branding

router = APIRouter(prefix="/api/branding", tags=["branding"])


@router.get("/logo")
async def get_logo():
    found = branding.logo_file()
    if not found:
        raise HTTPException(404, "尚未上传 Logo")
    path, mime = found
    return FileResponse(path, media_type=mime, headers={
        "Cache-Control": "public, max-age=300",
        "X-Content-Type-Options": "nosniff",
    })
