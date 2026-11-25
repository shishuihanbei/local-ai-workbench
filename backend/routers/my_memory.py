"""用户自助长期记忆：只看和操作自己的条目。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import load_config
from ..db import audit, fetch_one
from ..security import current_user
from ..services import memory

router = APIRouter(prefix="/api/my/memory", tags=["my-memory"])


class ToggleBody(BaseModel):
    enabled: bool


class AddBody(BaseModel):
    content: str
    kind: str = "fact"


class UpdateBody(BaseModel):
    content: str
    kind: str | None = None


@router.get("")
async def status(user: dict = Depends(current_user)):
    cfg = load_config()
    global_enabled = bool(cfg.get("memory_enabled", False))
    user_enabled = await memory.user_enabled(user["id"])
    return {
        "global_enabled": global_enabled,
        "user_enabled": user_enabled,
        "effective": global_enabled and user_enabled,
        "items": await memory.list_for_user(user["id"]),
        "stats": await memory.stats_for_user(user["id"]),
        "max_items": int(cfg.get("memory_max_items") or 40),
    }


@router.post("/toggle")
async def toggle(body: ToggleBody, user: dict = Depends(current_user)):
    await memory.set_user_enabled(user["id"], bool(body.enabled))
    await audit(user, "memory.my.toggle", detail="on" if body.enabled else "off")
    global_enabled = memory.enabled()
    return {"ok": True, "user_enabled": bool(body.enabled),
            "effective": global_enabled and bool(body.enabled),
            "global_enabled": global_enabled}


@router.post("/items")
async def add_item(body: AddBody, user: dict = Depends(current_user)):
    got = await memory.add(user["id"], body.content, kind=body.kind, source="manual")
    if not got:
        raise HTTPException(400, "内容太短或为空")
    await audit(user, "memory.my.add", detail=body.content[:60])
    return {"ok": True, "item": got}


@router.patch("/items/{memory_id}")
async def edit_item(memory_id: int, body: UpdateBody, user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT id FROM memories WHERE id=? AND user_id=?", (memory_id, user["id"]))
    if not row:
        raise HTTPException(404, "记忆不存在")
    got = await memory.update(memory_id, body.content, body.kind)
    if not got:
        raise HTTPException(400, "内容太短或为空")
    await audit(user, "memory.my.update", target=str(memory_id))
    return {"ok": True, "item": got}


@router.delete("/items/{memory_id}")
async def delete_item(memory_id: int, user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT id FROM memories WHERE id=? AND user_id=?", (memory_id, user["id"]))
    if not row:
        raise HTTPException(404, "记忆不存在")
    await memory.delete(memory_id)
    await audit(user, "memory.my.delete", target=str(memory_id))
    return {"ok": True}


@router.post("/clear")
async def clear(user: dict = Depends(current_user)):
    total = await memory.clear_for_user(user["id"])
    await audit(user, "memory.my.clear", detail=f"{total}")
    return {"ok": True, "removed": total}
