"""口令哈希、会话、CSRF、登录限流与权限依赖。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from fastapi import Cookie, Depends, HTTPException, Request

from .config import load_config, secret_key
from .db import connect, execute, fetch_one

SESSION_COOKIE = "wb_session"
CSRF_COOKIE = "wb_csrf"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

# ------------------------------------------------------------------ 口令
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                        r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n),
                            r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "密码至少 8 位"
    if password.isdigit() or password.isalpha():
        return "密码不能全是数字或全是字母"
    return None


# ------------------------------------------------------------------ 会话
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(user_id: int, ip: str, ua: str) -> tuple[str, int]:
    """创建会话，返回 (会话令牌, 会话ID)。"""
    token = secrets.token_urlsafe(40)
    hours = int(load_config().get("session_hours", 72))
    now = time.time()
    db = await connect()
    try:
        cur = await db.execute(
            "INSERT INTO sessions(user_id,token_hash,created_at,expires_at,ip,ua) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, _token_hash(token), now, now + hours * 3600, ip, ua[:300]))
        await db.commit()
        sid = cur.lastrowid
    finally:
        await db.close()
    return token, int(sid)


async def session_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    row = await fetch_one(
        "SELECT s.id sid, s.expires_at, u.id, u.username, u.role, u.disabled, u.admin_role_id "
        "FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.revoked=0",
        (_token_hash(token),))
    if not row:
        return None
    if row["expires_at"] < time.time() or row["disabled"]:
        await execute("UPDATE sessions SET revoked=1 WHERE id=?", (row["sid"],))
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "admin_role_id": row["admin_role_id"], "sid": row["sid"]}


async def revoke_session(sid: int) -> None:
    await execute("UPDATE sessions SET revoked=1 WHERE id=?", (sid,))


async def revoke_user_sessions(user_id: int, keep_sid: int | None = None) -> None:
    if keep_sid:
        await execute("UPDATE sessions SET revoked=1 WHERE user_id=? AND id<>?", (user_id, keep_sid))
    else:
        await execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


# ------------------------------------------------------------------ Bearer 令牌
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def create_access_token(user_id: int, sid: int, username: str, role: str,
                        hours: int | None = None) -> tuple[str, int]:
    """返回 (token, 有效期秒)。前后端分离部署时前端用 Bearer 调用。"""
    hours = hours or int(load_config().get("token_hours", 24))
    exp = int(time.time() + hours * 3600)
    payload = {"u": user_id, "s": sid, "n": username, "r": role, "e": exp}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(secret_key().encode(), body.encode(), hashlib.sha256).digest())
    return f"v1.{body}.{sig}", int(hours * 3600)


def verify_access_token(token: str) -> dict[str, Any] | None:
    try:
        prefix, body, sig = token.split(".")
        if prefix != "v1":
            return None
        expect = _b64e(hmac.new(secret_key().encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("e", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


async def user_from_any_token(token: str) -> dict[str, Any] | None:
    return await user_from_access_token(token) or await session_user(token)


async def user_from_access_token(token: str) -> dict[str, Any] | None:
    payload = verify_access_token(token)
    if not payload:
        return None
    row = await fetch_one(
        "SELECT s.id sid, s.revoked, s.expires_at, u.username, u.role, u.disabled, u.admin_role_id "
        "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.user_id=?",
        (payload["s"], payload["u"]))
    if not row or row["revoked"] or row["disabled"] or row["expires_at"] < time.time():
        return None
    return {"id": payload["u"], "username": row["username"], "role": row["role"],
            "admin_role_id": row["admin_role_id"], "sid": row["sid"]}


def check_csrf(request: Request, csrf_cookie: str | None, csrf_header: str | None) -> bool:
    if csrf_cookie and csrf_header and hmac.compare_digest(csrf_cookie, csrf_header):
        return True
    # 前后端分离：Bearer 令牌本身不受 CSRF 影响
    auth = request.headers.get("authorization", "")
    return auth.lower().startswith("bearer ") and len(auth) > 20


async def current_user(request: Request,
                       wb_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                       ) -> dict[str, Any]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        raw = auth.split(" ", 1)[1].strip()
        user = await user_from_access_token(raw) or await session_user(raw)
        if user:
            return user
    user = await session_user(wb_session)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或令牌已失效")
    return user


# 管理端模块权限：角色勾选这些模块后，只能访问对应路径。
PERMISSION_MODULES: dict[str, str] = {
    "overview": "概览",
    "org": "企业设置",
    "moderation": "内容安全",
    "requests": "调用记录",
    "users": "用户与组织",
    "auth": "登录方式",
    "providers": "供应商",
    "routes": "路由规则",
    "api": "API Key",
    "network": "网络与穿透",
    "websearch": "联网检索",
    "parsing": "附件解析",
    "deploy": "部署与模型引擎",
    "cluster": "多机算力池",
    "models": "模型目录",
    "kb": "知识库",
    "library": "资料库",
    "memory": "长期记忆",
    "backup": "备份迁移",
    "audit": "审计日志",
    "database": "数据库中心",
    "share": "网站分享",
    "skills": "技能",
    "prompts": "提示词中心",
    "front": "前台功能",
    "agents": "智能体",
    "partners": "伙伴",
    "squads": "小队",
    "announcements": "公告",
    "tickets": "服务台",
    "conv_shares": "对话分享",
}

# 顺序很重要：先匹配更长的具体前缀。
ADMIN_PATH_PERMISSIONS: list[tuple[str, str]] = [
    ("/api/admin/overview", "overview"),
    ("/api/admin/org", "org"),
    ("/api/admin/moderation", "moderation"),
    ("/api/admin/agents", "agents"),
    ("/api/admin/partners", "partners"),
    ("/api/admin/squads", "squads"),
    ("/api/admin/announcements", "announcements"),
    ("/api/admin/tickets", "tickets"),
    ("/api/admin/shares", "conv_shares"),
    ("/api/admin/requests", "requests"),
    ("/api/admin/providers", "providers"),
    ("/api/admin/routes", "routes"),
    ("/api/admin/auth-providers", "auth"),
    ("/api/admin/audit", "audit"),
    ("/api/admin/skills", "skills"),
    ("/api/admin/prompts", "prompts"),
    ("/api/admin/front-features", "front"),
    ("/api/admin/front-icons", "front"),
    ("/api/admin/cluster", "cluster"),
    ("/api/admin/memory", "memory"),
    ("/api/admin/database", "database"),
    ("/api/admin/roles", "users"),
    ("/api/admin/groups", "users"),
    ("/api/admin/users", "users"),
    ("/api/admin/cache", "overview"),
    ("/api/users", "users"),
    ("/api/library", "library"),
    ("/api/kb", "kb"),
    ("/api/models", "models"),
    ("/api/system/backup", "backup"),
    ("/api/system/backups", "backup"),
    ("/api/system/restore", "backup"),
    ("/api/system/migration", "backup"),
    ("/api/system/share", "share"),
    ("/api/system/shares", "share"),
    ("/api/system/open-migration-folder", "backup"),
    ("/api/system/open-share-folder", "share"),
    ("/api/system/local-deploy", "deploy"),
    ("/api/system/local-platforms", "deploy"),
    ("/api/system/install-", "deploy"),
    ("/api/system/install-status", "deploy"),
    ("/api/system/hardware", "deploy"),
    ("/api/system/network-check", "deploy"),
    ("/api/system/websearch", "websearch"),
    ("/api/admin/uploads", "parsing"),
    ("/api/system", "deploy"),
    ("/api/tunnel", "network"),
    ("/api/api-keys", "api"),
    ("/api/admin", "overview"),
]

# 这些接口被多个页面共用，且只涉及低风险开关；任何管理员角色都可访问。
SAFE_ADMIN_PATHS = {"/api/system/settings"}


def permission_for_path(path: str) -> str:
    for prefix, module in ADMIN_PATH_PERMISSIONS:
        if path == prefix or path.startswith(prefix + "/"):
            return module
    return "overview"


async def admin_permissions(user: dict[str, Any]) -> list[str]:
    """当前管理员可访问的模块；未绑定角色的管理员视为全权限。"""
    if user.get("role") != "admin":
        return []
    role_id = user.get("admin_role_id")
    if not role_id:
        return sorted(PERMISSION_MODULES)
    role = await fetch_one("SELECT permissions,is_super FROM admin_roles WHERE id=?", (role_id,))
    if not role:
        return []
    if role["is_super"]:
        return sorted(PERMISSION_MODULES)
    try:
        return [p for p in json.loads(role["permissions"] or "[]") if p in PERMISSION_MODULES]
    except Exception:
        return []


async def admin_user(request: Request,
                     user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    role_id = user.get("admin_role_id")
    if not role_id:
        # 未绑定自定义角色的管理员是超级管理员，保持旧版行为
        user["admin_permissions"] = sorted(PERMISSION_MODULES)
        return user
    role = await fetch_one(
        "SELECT id,name,permissions,is_super FROM admin_roles WHERE id=?", (role_id,))
    if not role:
        raise HTTPException(status_code=403, detail="管理员角色不存在，请联系超级管理员")
    if role["is_super"]:
        permissions = sorted(PERMISSION_MODULES)
    else:
        try:
            permissions = [p for p in json.loads(role["permissions"] or "[]")
                           if p in PERMISSION_MODULES]
        except Exception:
            permissions = []
    module = permission_for_path(request.url.path)
    if request.url.path.rstrip("/") not in SAFE_ADMIN_PATHS and module not in permissions:
        raise HTTPException(
            status_code=403,
            detail=f"当前管理员角色「{role['name']}」没有「{PERMISSION_MODULES.get(module, module)}」权限")
    user["admin_permissions"] = permissions
    user["admin_role_name"] = role["name"]
    return user


async def any_user_or_none(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE)
    return await session_user(token)


# ------------------------------------------------------------------ 登录限流
_FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW, LOCK = 5, 600, 900


def login_blocked(key: str) -> int:
    """返回剩余锁定秒数；0 表示可尝试。"""
    now = time.time()
    hist = [t for t in _FAILS.get(key, []) if now - t < WINDOW]
    _FAILS[key] = hist
    if len(hist) >= MAX_FAILS:
        until = hist[-1] + LOCK
        if until > now:
            return int(until - now)
        _FAILS[key] = []
    return 0


def note_login_fail(key: str) -> None:
    _FAILS.setdefault(key, []).append(time.time())


def clear_login_fail(key: str) -> None:
    _FAILS.pop(key, None)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""
