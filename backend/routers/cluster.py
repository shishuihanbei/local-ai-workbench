"""多机算力池管理 API。"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import audit
from ..security import admin_user
from ..services import cluster, secrets_store

router = APIRouter(prefix="/api/admin/cluster", tags=["cluster"])


class NodeBody(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    weight: int = 1
    max_concurrency: int = 4
    enabled: bool = True
    note: str = ""


class NodePatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    weight: int | None = None
    max_concurrency: int | None = None
    enabled: bool | None = None
    note: str | None = None


class ProbeBody(BaseModel):
    base_url: str
    api_key: str = ""


class MemberBody(BaseModel):
    node_id: int
    remote_model: str
    weight: int = 1
    enabled: bool = True


class PoolBody(BaseModel):
    name: str
    strategy: str = "weighted_least"
    timeout: float = 30
    retries: int = 1
    enabled: bool = True
    note: str = ""
    members: list[MemberBody] = Field(default_factory=list)


class PoolPatch(BaseModel):
    name: str | None = None
    strategy: str | None = None
    timeout: float | None = None
    retries: int | None = None
    enabled: bool | None = None
    note: str | None = None
    members: list[MemberBody] | None = None


def _public_pool(p: dict) -> dict:
    if not p:
        return {}
    return {
        "id": p["id"], "name": p["name"], "strategy": p.get("strategy"),
        "timeout": p.get("timeout"), "retries": p.get("retries"),
        "enabled": bool(p.get("enabled")), "note": p.get("note") or "",
        "members": p.get("members") or [],
    }


@router.get("")
async def overview(user: dict = Depends(admin_user)):
    nodes = await cluster.list_nodes()
    pools = await cluster.list_pools()
    stats = {
        "nodes": len(nodes),
        "online": sum(1 for n in nodes if n["status"] == "online"),
        "active": sum(n["active"] for n in nodes),
        "pools": sum(1 for p in pools if p["enabled"]),
        "pool_models": [p["name"] for p in pools if p["enabled"]],
    }
    return {"nodes": nodes, "pools": pools, "stats": stats,
            "strategies": [
                {"key": "weighted_least", "label": "加权最少连接"},
                {"key": "round_robin", "label": "轮询"},
            ]}


@router.post("/probe")
async def probe(body: ProbeBody, user: dict = Depends(admin_user)):
    result = await cluster.probe_node({
        "base_url": body.base_url,
        "api_key": secrets_store.encrypt(body.api_key) if body.api_key else "",
    })
    return result


@router.post("/nodes")
async def add_node(body: NodeBody, user: dict = Depends(admin_user)):
    try:
        node_id = await cluster.create_node(
            name=body.name, base_url=body.base_url, api_key=body.api_key,
            weight=body.weight, max_concurrency=body.max_concurrency,
            note=body.note, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    node = await fetch_one_public(node_id)
    await audit(user, "cluster.node.add", detail=body.name)
    return {"ok": True, "node": node}


@router.patch("/nodes/{node_id}")
async def edit_node(node_id: int, body: NodePatch, user: dict = Depends(admin_user)):
    try:
        await cluster.update_node(node_id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await audit(user, "cluster.node.edit", target=str(node_id))
    return {"ok": True, "node": await fetch_one_public(node_id)}


@router.delete("/nodes/{node_id}")
async def remove_node(node_id: int, user: dict = Depends(admin_user)):
    await cluster.delete_node(node_id)
    await audit(user, "cluster.node.delete", target=str(node_id))
    return {"ok": True}


@router.post("/nodes/{node_id}/test")
async def test_node(node_id: int, user: dict = Depends(admin_user)):
    node = await fetch_node(node_id)
    if not node:
        raise HTTPException(404, "节点不存在")
    result = await cluster.refresh_node(node)
    return result


@router.post("/refresh")
async def refresh(user: dict = Depends(admin_user)):
    results = await cluster.refresh_all()
    return {"ok": True, "items": results, "ts": time.time()}


@router.post("/pools")
async def add_pool(body: PoolBody, user: dict = Depends(admin_user)):
    try:
        pool_id = await cluster.create_pool(
            name=body.name, strategy=body.strategy, timeout=body.timeout,
            retries=body.retries, note=body.note,
            members=[m.model_dump() for m in body.members])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    pools = await cluster.list_pools()
    pool = next((p for p in pools if p["id"] == pool_id), None)
    await audit(user, "cluster.pool.add", detail=body.name)
    return {"ok": True, "pool": _public_pool(pool or {})}


@router.patch("/pools/{pool_id}")
async def edit_pool(pool_id: int, body: PoolPatch, user: dict = Depends(admin_user)):
    data: dict[str, Any] = body.model_dump(exclude_none=True)
    if body.members is not None:
        data["members"] = [m.model_dump() for m in body.members]
    try:
        await cluster.update_pool(pool_id, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    pools = await cluster.list_pools()
    pool = next((p for p in pools if p["id"] == pool_id), None)
    await audit(user, "cluster.pool.edit", target=str(pool_id))
    return {"ok": True, "pool": _public_pool(pool or {})}


@router.delete("/pools/{pool_id}")
async def remove_pool(pool_id: int, user: dict = Depends(admin_user)):
    await cluster.delete_pool(pool_id)
    await audit(user, "cluster.pool.delete", target=str(pool_id))
    return {"ok": True}


# 兼容包内的小工具，避免 router 依赖 admin.py 的私有函数
async def fetch_node(node_id: int) -> dict | None:
    from ..db import fetch_one
    return await fetch_one("SELECT * FROM cluster_nodes WHERE id=?", (node_id,))


async def fetch_one_public(node_id: int) -> dict | None:
    from ..db import fetch_one
    row = await fetch_one("SELECT * FROM cluster_nodes WHERE id=?", (node_id,))
    return cluster._public_node(row) if row else None
