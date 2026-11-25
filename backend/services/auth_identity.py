"""认证身份：一个账号可绑定多种登录方式。

用户名、手机号、邮箱、QQ、微信都落到同一张 auth_identities 表，
登录成功后再映射到 users.id。这样后续加登录方式不用改用户表。
"""
from __future__ import annotations

import json
import time

from ..db import execute, fetch_all, fetch_one


def normalize_uid(provider: str, uid: str) -> str:
    value = str(uid or "").strip()
    if provider in ("username", "email"):
        return value.lower()
    if provider == "phone":
        return "".join(ch for ch in value if ch.isdigit() or ch == "+")
    return value


async def link_identity(user_id: int, provider: str, uid: str, display_name: str = "",
                        meta: dict | None = None) -> int:
    """绑定身份；同一 provider+uid 已存在时直接返回原记录。"""
    provider = provider.strip().lower()
    uid = normalize_uid(provider, uid)
    if not uid:
        raise ValueError("身份标识为空")
    row = await fetch_one(
        "SELECT id,user_id FROM auth_identities WHERE provider=? AND provider_uid=?",
        (provider, uid))
    if row:
        return int(row["id"])
    return await execute(
        "INSERT INTO auth_identities(user_id,provider,provider_uid,display_name,meta,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (user_id, provider, uid, display_name, json.dumps(meta or {}, ensure_ascii=False), time.time()))


async def resolve_identity(provider: str, uid: str) -> dict | None:
    provider = provider.strip().lower()
    uid = normalize_uid(provider, uid)
    return await fetch_one(
        "SELECT i.*,u.username,u.role,u.disabled FROM auth_identities i "
        "JOIN users u ON u.id=i.user_id WHERE i.provider=? AND i.provider_uid=?",
        (provider, uid))


async def list_identities(user_id: int) -> list[dict]:
    rows = await fetch_all(
        "SELECT id,provider,provider_uid,display_name,created_at,last_login_at "
        "FROM auth_identities WHERE user_id=? ORDER BY id", (user_id,))
    for row in rows:
        provider = row["provider"]
        uid = row["provider_uid"]
        if provider == "email" and "@" in uid:
            name, domain = uid.split("@", 1)
            row["masked"] = f"{name[:2]}***@{domain}"
        elif provider == "phone" and len(uid) >= 7:
            row["masked"] = f"{uid[:3]}****{uid[-4:]}"
        elif provider in ("qq", "wechat") and len(uid) > 8:
            row["masked"] = f"{uid[:4]}…{uid[-4:]}"
        else:
            row["masked"] = uid
    return rows


async def touch_identity(identity_id: int) -> None:
    await execute("UPDATE auth_identities SET last_login_at=? WHERE id=?", (time.time(), identity_id))
