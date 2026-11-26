"""独立引擎清单与一键安装接口。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..db import audit
from ..security import admin_user, current_user
from ..services import engine_install, engines

router = APIRouter(prefix="/api/engines", tags=["engines"])


@router.get("")
async def list_engines(user: dict = Depends(current_user)):
    state = engines.status()
    items = engines.catalog(state)
    for item in items:
        item["progress"] = engine_install.status(item["key"])
    return {
        "items": items,
        "busy": engine_install.running(),
        "platform": state.get("platform", ""),
        "gpu": state.get("gpu", False),
        "gpu_vram_gb": state.get("gpu_vram_gb", 0),
    }


@router.post("/{key}/install")
async def install(key: str, user: dict = Depends(admin_user)):
    if key not in engines.ENGINE_CATALOG:
        raise HTTPException(404, "未知的独立引擎")
    try:
        res = await asyncio.to_thread(engine_install.start, key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit(user, "engine.install", key, engines.ENGINE_CATALOG[key]["label"])
    return res


@router.get("/{key}/install-progress")
async def install_progress(key: str, user: dict = Depends(current_user)):
    if key not in engines.ENGINE_CATALOG:
        raise HTTPException(404, "未知的独立引擎")
    return engine_install.status(key)
