"""多机算力池：节点注册、统一模型池和加权调度。

这一层只负责“把请求分到哪台机器”，不改变单台机器上的推理方式。
每个节点都必须是 OpenAI 兼容服务：`/v1/models` 和 `/v1/chat/completions`。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from ..db import execute, fetch_all, fetch_one
from . import secrets_store

_active: dict[int, int] = {}
_rr: dict[int, int] = {}
_monitor_task: asyncio.Task | None = None
_MONITOR_SECONDS = 30


def normalize_base(value: str) -> str:
    """统一成带 /v1 的根地址；空协议自动补 http://。"""
    text = (value or "").strip()[:300].rstrip("/")
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    if not text.endswith("/v1"):
        text += "/v1"
    return text


def _mask(key: str) -> str:
    if not key:
        return ""
    return "****" + key[-4:] if len(key) > 4 else "****"


def _json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x)]
    try:
        value = json.loads(raw or "[]")
        return [str(x) for x in value if str(x)] if isinstance(value, list) else []
    except Exception:
        return []


async def probe_node(node: dict) -> dict[str, Any]:
    """探测节点的 OpenAI 接口，不抛异常，结果直接给页面用。"""
    base = normalize_base(node.get("base_url") or "")
    if not base:
        return {"ok": False, "models": [], "latency_ms": 0, "detail": "没有填写节点地址", "status": 0}
    key = ""
    try:
        key = secrets_store.decrypt(node.get("api_key") or "")
    except Exception:
        key = ""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{base}/models", headers=headers)
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            return {"ok": False, "models": [], "latency_ms": ms,
                    "detail": f"HTTP {r.status_code}: {r.text[:160]}", "status": r.status_code}
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        rows = payload.get("data") if isinstance(payload, dict) else None
        if rows is None and isinstance(payload, dict):
            rows = payload.get("models")
        names: list[str] = []
        for row in rows or []:
            if isinstance(row, dict):
                name = row.get("id") or row.get("name")
            else:
                name = row
            if name:
                names.append(str(name))
        return {"ok": True, "models": names[:40], "latency_ms": ms,
                "detail": f"已连接 · {len(names)} 个模型", "status": 200}
    except Exception as exc:
        return {"ok": False, "models": [], "latency_ms": int((time.monotonic() - t0) * 1000),
                "detail": f"未连接：{type(exc).__name__}", "status": 0}


async def refresh_node(node: dict | int) -> dict[str, Any]:
    if isinstance(node, int):
        node = await fetch_one("SELECT * FROM cluster_nodes WHERE id=?", (node,)) or {}
    if not node:
        return {"ok": False, "detail": "节点不存在"}
    result = await probe_node(node)
    now = time.time()
    status = "online" if result["ok"] else "offline"
    await execute(
        "UPDATE cluster_nodes SET status=?,models=?,latency_ms=?,last_error=?,last_check_at=?,"
        "last_ok_at=CASE WHEN ?='online' THEN ? ELSE last_ok_at END WHERE id=?",
        (status, json.dumps(result.get("models") or [], ensure_ascii=False),
         int(result.get("latency_ms") or 0), "" if result["ok"] else str(result.get("detail") or "")[:300],
         now, status, now, node["id"]),
    )
    return {**result, "status": status, "node_id": node["id"]}


async def refresh_all() -> list[dict[str, Any]]:
    nodes = await fetch_all("SELECT * FROM cluster_nodes WHERE enabled=1 ORDER BY id")
    if not nodes:
        return []
    return list(await asyncio.gather(*(refresh_node(n) for n in nodes)))


def _public_node(row: dict) -> dict[str, Any]:
    key = ""
    try:
        key = secrets_store.decrypt(row.get("api_key") or "")
    except Exception:
        key = ""
    return {
        "id": row["id"],
        "name": row["name"],
        "base_url": row["base_url"],
        "api_key_masked": _mask(key),
        "has_key": bool(key),
        "weight": int(row.get("weight") or 1),
        "max_concurrency": int(row.get("max_concurrency") or 4),
        "enabled": bool(row.get("enabled")),
        "status": row.get("status") or "unknown",
        "models": _json_list(row.get("models")),
        "latency_ms": int(row.get("latency_ms") or 0),
        "last_error": row.get("last_error") or "",
        "last_check_at": row.get("last_check_at"),
        "last_ok_at": row.get("last_ok_at"),
        "note": row.get("note") or "",
        "active": active_count(row["id"]),
    }


async def list_nodes() -> list[dict[str, Any]]:
    rows = await fetch_all("SELECT * FROM cluster_nodes ORDER BY id")
    return [_public_node(r) for r in rows]


async def list_pools() -> list[dict[str, Any]]:
    pools = await fetch_all("SELECT * FROM cluster_pools ORDER BY id")
    out: list[dict[str, Any]] = []
    for p in pools:
        members = await fetch_all(
            "SELECT m.id,m.node_id,m.remote_model,m.weight,m.enabled,"
            "n.name node_name,n.status node_status,n.max_concurrency,n.base_url "
            "FROM cluster_members m JOIN cluster_nodes n ON n.id=m.node_id "
            "WHERE m.pool_id=? ORDER BY m.id", (p["id"],))
        for m in members:
            m["enabled"] = bool(m["enabled"])
            m["active"] = active_count(m["node_id"])
        out.append({**p, "enabled": bool(p["enabled"]), "members": members})
    return out


async def pool_by_name(name: str) -> dict | None:
    name = (name or "").strip()
    if not name:
        return None
    return await fetch_one("SELECT * FROM cluster_pools WHERE name=? AND enabled=1", (name,))


async def create_node(*, name: str, base_url: str, api_key: str = "", weight: int = 1,
                      max_concurrency: int = 4, note: str = "", enabled: bool = True) -> int:
    name = (name or "").strip()[:80]
    base = normalize_base(base_url)
    if not name or not base:
        raise ValueError("节点名称和地址不能为空")
    if await fetch_one("SELECT id FROM cluster_nodes WHERE name=?", (name,)):
        raise ValueError("同名节点已存在")
    return await execute(
        "INSERT INTO cluster_nodes(name,base_url,api_key,weight,max_concurrency,enabled,note,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (name, base, secrets_store.encrypt(api_key), max(1, min(int(weight or 1), 100)),
         max(1, min(int(max_concurrency or 4), 100)), 1 if enabled else 0, note[:300], time.time()))


async def update_node(node_id: int, data: dict[str, Any]) -> None:
    row = await fetch_one("SELECT * FROM cluster_nodes WHERE id=?", (node_id,))
    if not row:
        raise ValueError("节点不存在")
    allowed = {"name", "base_url", "api_key", "weight", "max_concurrency", "enabled", "note"}
    values: dict[str, Any] = {k: v for k, v in data.items() if k in allowed and v is not None}
    if "name" in values:
        values["name"] = str(values["name"]).strip()[:80]
        if not values["name"]:
            raise ValueError("节点名称不能为空")
        other = await fetch_one("SELECT id FROM cluster_nodes WHERE name=? AND id<>?",
                                (values["name"], node_id))
        if other:
            raise ValueError("同名节点已存在")
    if "base_url" in values:
        values["base_url"] = normalize_base(str(values["base_url"]))
        if not values["base_url"]:
            raise ValueError("节点地址不能为空")
    if "api_key" in values:
        values["api_key"] = secrets_store.encrypt(str(values["api_key"]))
    if "weight" in values:
        values["weight"] = max(1, min(int(values["weight"]), 100))
    if "max_concurrency" in values:
        values["max_concurrency"] = max(1, min(int(values["max_concurrency"]), 100))
    if "enabled" in values:
        values["enabled"] = 1 if values["enabled"] else 0
    if not values:
        return
    sets = ", ".join(f"{k}=?" for k in values)
    await execute(f"UPDATE cluster_nodes SET {sets} WHERE id=?", list(values.values()) + [node_id])


async def delete_node(node_id: int) -> None:
    await execute("DELETE FROM cluster_nodes WHERE id=?", (node_id,))


async def create_pool(*, name: str, strategy: str = "weighted_least", timeout: float = 30,
                      retries: int = 1, note: str = "", members: list[dict] | None = None) -> int:
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("统一模型名不能为空")
    if await fetch_one("SELECT id FROM cluster_pools WHERE name=?", (name,)):
        raise ValueError("同名模型池已存在")
    if strategy not in ("weighted_least", "round_robin"):
        strategy = "weighted_least"
    pool_id = await execute(
        "INSERT INTO cluster_pools(name,strategy,timeout,retries,note,created_at) VALUES(?,?,?,?,?,?)",
        (name, strategy, max(3, min(float(timeout or 30), 300)), max(0, min(int(retries or 0), 5)),
         note[:300], time.time()))
    await replace_members(pool_id, members or [])
    return pool_id


async def replace_members(pool_id: int, members: list[dict]) -> None:
    await execute("DELETE FROM cluster_members WHERE pool_id=?", (pool_id,))
    for item in members:
        try:
            node_id = int(item.get("node_id"))
            remote_model = str(item.get("remote_model") or "").strip()[:160]
            weight = max(1, min(int(item.get("weight") or 1), 100))
            enabled = 1 if item.get("enabled", True) else 0
        except (TypeError, ValueError):
            continue
        if not remote_model:
            continue
        if not await fetch_one("SELECT id FROM cluster_nodes WHERE id=?", (node_id,)):
            continue
        await execute(
            "INSERT OR IGNORE INTO cluster_members(pool_id,node_id,remote_model,weight,enabled) "
            "VALUES(?,?,?,?,?)", (pool_id, node_id, remote_model, weight, enabled))


async def update_pool(pool_id: int, data: dict[str, Any]) -> None:
    row = await fetch_one("SELECT * FROM cluster_pools WHERE id=?", (pool_id,))
    if not row:
        raise ValueError("模型池不存在")
    allowed = {"name", "strategy", "timeout", "retries", "enabled", "note"}
    values: dict[str, Any] = {k: v for k, v in data.items() if k in allowed and v is not None}
    if "name" in values:
        values["name"] = str(values["name"]).strip()[:80]
        if not values["name"]:
            raise ValueError("统一模型名不能为空")
        other = await fetch_one("SELECT id FROM cluster_pools WHERE name=? AND id<>?",
                                (values["name"], pool_id))
        if other:
            raise ValueError("同名模型池已存在")
    if "strategy" in values and values["strategy"] not in ("weighted_least", "round_robin"):
        values["strategy"] = "weighted_least"
    if "timeout" in values:
        values["timeout"] = max(3, min(float(values["timeout"]), 300))
    if "retries" in values:
        values["retries"] = max(0, min(int(values["retries"]), 5))
    if "enabled" in values:
        values["enabled"] = 1 if values["enabled"] else 0
    if values:
        sets = ", ".join(f"{k}=?" for k in values)
        await execute(f"UPDATE cluster_pools SET {sets} WHERE id=?",
                      list(values.values()) + [pool_id])
    if "members" in data and isinstance(data["members"], list):
        await replace_members(pool_id, data["members"])


async def delete_pool(pool_id: int) -> None:
    await execute("DELETE FROM cluster_pools WHERE id=?", (pool_id,))


def active_count(node_id: int) -> int:
    return int(_active.get(int(node_id), 0))


def begin(node_id: int) -> None:
    _active[int(node_id)] = active_count(node_id) + 1


def end(node_id: int) -> None:
    key = int(node_id)
    _active[key] = max(0, active_count(key) - 1)


async def record_success(node_id: int, latency_ms: int = 0) -> None:
    await execute(
        "UPDATE cluster_nodes SET status='online',last_ok_at=?,last_error='',"
        "latency_ms=CASE WHEN ?>0 THEN ? ELSE latency_ms END WHERE id=?",
        (time.time(), max(0, int(latency_ms)), max(0, int(latency_ms)), node_id))


async def record_failure(node_id: int, error: str) -> None:
    await execute(
        "UPDATE cluster_nodes SET status='offline',last_error=?,last_check_at=? WHERE id=?",
        (str(error or "连接失败")[:300], time.time(), node_id))


async def candidates(pool_name: str) -> tuple[dict | None, list[dict[str, Any]]]:
    """返回池信息和排好序的候选节点。"""
    pool = await pool_by_name(pool_name)
    if not pool:
        return None, []
    rows = await fetch_all(
        "SELECT m.id member_id,m.node_id,m.remote_model,m.weight member_weight,m.enabled member_enabled,"
        "n.name node_name,n.base_url,n.api_key,n.weight node_weight,n.status,n.max_concurrency,n.latency_ms "
        "FROM cluster_members m JOIN cluster_nodes n ON n.id=m.node_id "
        "WHERE m.pool_id=? AND m.enabled=1 AND n.enabled=1 ORDER BY m.id", (pool["id"],))
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            key = secrets_store.decrypt(row.get("api_key") or "")
        except Exception:
            key = ""
        remote_model = str(row.get("remote_model") or "").strip()
        if not remote_model:
            continue
        active = active_count(row["node_id"])
        cap = max(1, int(row.get("max_concurrency") or 4))
        weight = max(1, int(row.get("member_weight") or 1)) * max(1, int(row.get("node_weight") or 1))
        status_rank = 0 if row.get("status") == "online" else (1 if row.get("status") != "offline" else 2)
        score = (active + 0.25) / weight
        if active >= cap:
            score *= 20
        items.append({
            "node_id": row["node_id"],
            "node_name": row["node_name"],
            "base": str(row["base_url"]).rstrip("/"),
            "key": key,
            "model": remote_model,
            "weight": weight,
            "max_concurrency": cap,
            "active": active,
            "latency_ms": int(row.get("latency_ms") or 0),
            "status": row.get("status") or "unknown",
            "_rank": status_rank,
            "_score": score,
            "_member_id": row["member_id"],
        })
    if pool.get("strategy") == "round_robin" and items:
        start = _rr.get(int(pool["id"]), 0) % len(items)
        items = items[start:] + items[:start]
        _rr[int(pool["id"])] = (start + 1) % len(items)
    else:
        items.sort(key=lambda x: (x["_rank"], x["_score"], x["node_id"]))
    for item in items:
        item.pop("_rank", None)
        item.pop("_score", None)
        item.pop("_member_id", None)
    return pool, items


async def _monitor_loop() -> None:
    while True:
        try:
            await refresh_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(_MONITOR_SECONDS)


def start_monitor() -> None:
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(_monitor_loop())


async def stop_monitor() -> None:
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
    _monitor_task = None
