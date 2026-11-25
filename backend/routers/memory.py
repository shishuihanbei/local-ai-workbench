"""长期记忆管理：全局开关、条目查看、手动添加、编辑与删除。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import load_config, save_config
from ..db import audit, fetch_all, fetch_one
from ..security import admin_user
from ..services import memory

router = APIRouter(prefix="/api/admin/memory", tags=["memory"])


class ToggleBody(BaseModel):
    enabled: bool


class AddBody(BaseModel):
    content: str
    user_id: int | None = None
    kind: str = "fact"


class UpdateBody(BaseModel):
    content: str
    kind: str | None = None


@router.get("")
async def status(user: dict = Depends(admin_user)):
    cfg = load_config()
    items = await memory.list_for_admin()
    users = await fetch_all(
        "SELECT id,username,memory_enabled FROM users ORDER BY id")
    return {
        "enabled": bool(cfg.get("memory_enabled", False)),
        "current_user_id": user["id"],
        "users": users,
        "items": items,
        "stats": await memory.stats(),
        "max_items": int(cfg.get("memory_max_items") or 40),
    }


@router.post("/toggle")
async def toggle(body: ToggleBody, user: dict = Depends(admin_user)):
    cfg = load_config()
    cfg["memory_enabled"] = bool(body.enabled)
    save_config(cfg)
    await audit(user, "memory.toggle", detail="on" if body.enabled else "off")
    return {"ok": True, "enabled": bool(body.enabled)}


@router.post("/items")
async def add_item(body: AddBody, user: dict = Depends(admin_user)):
    uid = int(body.user_id or user["id"])
    target = await fetch_one("SELECT id FROM users WHERE id=?", (uid,))
    if not target:
        raise HTTPException(404, "用户不存在")
    got = await memory.add(uid, body.content, kind=body.kind, source="manual")
    if not got:
        raise HTTPException(400, "内容太短或为空")
    await audit(user, "memory.add", target=str(uid), detail=body.content[:60])
    return {"ok": True, "item": got}


@router.patch("/items/{memory_id}")
async def edit_item(memory_id: int, body: UpdateBody, user: dict = Depends(admin_user)):
    got = await memory.update(memory_id, body.content, body.kind)
    if not got:
        raise HTTPException(404, "记忆不存在或内容为空")
    await audit(user, "memory.update", target=str(memory_id))
    return {"ok": True, "item": got}


@router.delete("/items/{memory_id}")
async def delete_item(memory_id: int, user: dict = Depends(admin_user)):
    if not await memory.delete(memory_id):
        raise HTTPException(404, "记忆不存在")
    await audit(user, "memory.delete", target=str(memory_id))
    return {"ok": True}
