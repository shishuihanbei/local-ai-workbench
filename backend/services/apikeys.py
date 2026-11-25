"""用户自建 API Key：只保存哈希，明文仅在生成时返回一次。"""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from ..db import execute, fetch_all, fetch_one
from . import access

PREFIX = "sk-wb-"
MAX_ACTIVE = 20


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _masked(prefix: str) -> str:
    return f"{prefix}…"


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "masked": _masked(row["prefix"]),
        "created_at": row["created_at"],
        "last_used_at": row.get("last_used_at"),
        "last_ip": row.get("last_ip") or "",
        "last_scope": row.get("last_scope") or "",
        "revoked": bool(row.get("revoked")),
        "username": row.get("username") or "",
    }


async def create(user: dict, name: str) -> tuple[str, dict[str, Any]]:
    name = (name or "").strip()[:40] or "默认密钥"
    active = await fetch_one(
        "SELECT COUNT(*) c FROM api_keys WHERE user_id=? AND revoked=0", (user["id"],))
    if int((active or {}).get("c") or 0) >= MAX_ACTIVE:
        raise ValueError(f"最多保留 {MAX_ACTIVE} 个有效密钥，请先撤销不用的")
    token = PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    row_id = await execute(
        "INSERT INTO api_keys(user_id,name,prefix,key_hash,created_at) VALUES(?,?,?,?,?)",
        (user["id"], name, token[:16], _hash(token), now))
    row = await fetch_one(
        "SELECT k.*, u.username FROM api_keys k JOIN users u ON u.id=k.user_id WHERE k.id=?",
        (row_id,))
    return token, _public(row or {})


async def list_keys(user: dict, all_users: bool = False) -> list[dict[str, Any]]:
    if all_users and user.get("role") == "admin":
        rows = await fetch_all(
            "SELECT k.*, u.username FROM api_keys k JOIN users u ON u.id=k.user_id "
            "ORDER BY k.created_at DESC LIMIT 200")
    else:
        rows = await fetch_all(
            "SELECT k.*, u.username FROM api_keys k JOIN users u ON u.id=k.user_id "
            "WHERE k.user_id=? ORDER BY k.created_at DESC LIMIT 200", (user["id"],))
    return [_public(r) for r in rows]


async def revoke(user: dict, key_id: int) -> bool:
    row = await fetch_one("SELECT id,user_id FROM api_keys WHERE id=?", (key_id,))
    if not row:
        return False
    if user.get("role") != "admin" and row["user_id"] != user["id"]:
        return False
    await execute("UPDATE api_keys SET revoked=1 WHERE id=?", (key_id,))
    return True


async def authenticate(raw: str, ip: str = "", scope: str = "") -> dict[str, Any] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    row = await fetch_one(
        "SELECT k.id key_id, k.name key_name, k.revoked, "
        "u.id, u.username, u.role, u.disabled "
        "FROM api_keys k JOIN users u ON u.id=k.user_id WHERE k.key_hash=?",
        (_hash(raw),))
    if not row or row["revoked"] or row["disabled"]:
        return None
    await execute(
        "UPDATE api_keys SET last_used_at=?, last_ip=?, last_scope=? WHERE id=?",
        (time.time(), ip[:64], scope[:10], row["key_id"]))
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "key_id": row["key_id"], "key_name": row["key_name"]}


async def models_for(user: dict) -> list[dict[str, Any]]:
    """API 可用的本地与第三方模型，按用户权限过滤。"""
    from ..config import load_config
    local_enabled = bool(load_config().get("local_enabled", True))
    allowed = await access.allowed_for(user)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    if local_enabled:
        for row in await fetch_all("SELECT key,alias,label,filename FROM models ORDER BY sort,key"):
            names = {row["key"]} | ({row["alias"]} if row.get("alias") else set())
            if allowed is not None and not (names & allowed):
                continue
            if row["key"] in seen:
                continue
            seen.add(row["key"])
            items.append({"id": row["key"], "label": row.get("label") or row["key"],
                          "owned_by": "local", "kind": "local"})
    for pool in await fetch_all("SELECT name,note FROM cluster_pools WHERE enabled=1 ORDER BY id"):
        name = str(pool.get("name") or "").strip()
        if not name or name in seen:
            continue
        if allowed is not None and name not in allowed:
            continue
        seen.add(name)
        items.append({"id": name, "label": name, "owned_by": "cluster", "kind": "cluster"})
    for p in await fetch_all("SELECT name,models FROM providers WHERE enabled=1 ORDER BY id"):
        for name in [x.strip() for x in (p["models"] or "").split(",") if x.strip()]:
            if name in seen:
                continue
            if allowed is not None and name not in allowed:
                continue
            seen.add(name)
            items.append({"id": name, "label": name, "owned_by": p["name"], "kind": "cloud"})
    return items
