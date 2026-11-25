"""用户管理（管理员）：账号、用户组、管理员角色和 Token 配额。"""
from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..db import audit, execute, fetch_all, fetch_one
from ..security import (PERMISSION_MODULES, admin_user, client_ip, hash_password,
                        password_problem, revoke_user_sessions, verify_password)
from ..services import access, auth_identity

router = APIRouter(prefix="/api/users", tags=["users"])


class UserBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    role: str = "user"
    allowed_models: list[str] | None = None
    group_id: int | None = None
    admin_role_id: int | None = None
    daily_token_limit: int = Field(default=0, ge=0)
    monthly_token_limit: int = Field(default=0, ge=0)


class PatchBody(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    new_password: str | None = None
    allowed_models: list[str] | None = None
    group_id: int | None = None
    admin_role_id: int | None = None
    daily_token_limit: int | None = Field(default=None, ge=0)
    monthly_token_limit: int | None = Field(default=None, ge=0)


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    parent_id: int | None = None
    leader_id: int | None = None
    sort: int = Field(default=0, ge=-9999, le=9999)


class RoleBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    permissions: list[str] = Field(default_factory=list)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    permissions: list[str] | None = None


class ImportBody(BaseModel):
    text: str
    default_group_id: int | None = None
    default_role: str = "user"
    default_daily_token_limit: int = Field(default=0, ge=0)
    default_monthly_token_limit: int = Field(default=0, ge=0)


def _allowed_out(raw) -> list[str] | str:
    value = access.parse(raw)
    return "*" if value is None else sorted(value)


def _limit(value) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _day_start() -> float:
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _month_start() -> float:
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def _role_out(row: dict) -> dict:
    try:
        perms = [p for p in json.loads(row.get("permissions") or "[]") if p in PERMISSION_MODULES]
    except Exception:
        perms = []
    return {"id": row["id"], "name": row["name"], "permissions": perms,
            "is_super": bool(row.get("is_super")), "created_at": row.get("created_at")}


async def _check_group(group_id: int | None) -> int | None:
    if group_id is None:
        return None
    if not await fetch_one("SELECT id FROM user_groups WHERE id=?", (group_id,)):
        raise HTTPException(400, "用户组不存在")
    return group_id


async def _check_role(role_id: int | None) -> int | None:
    if role_id is None:
        return None
    if not await fetch_one("SELECT id FROM admin_roles WHERE id=?", (role_id,)):
        raise HTTPException(400, "管理员角色不存在")
    return role_id


async def _check_parent(parent_id: int | None, gid: int | None = None) -> int | None:
    if parent_id is None:
        return None
    if not await fetch_one("SELECT id FROM user_groups WHERE id=?", (parent_id,)):
        raise HTTPException(400, "上级部门不存在")
    if gid is not None:
        if parent_id == gid:
            raise HTTPException(400, "上级部门不能是自己")
        cur = parent_id
        seen = set()
        while cur:
            if cur in seen:
                break
            seen.add(cur)
            if cur == gid:
                raise HTTPException(400, "不能把部门移动到自己的下级")
            row = await fetch_one("SELECT parent_id FROM user_groups WHERE id=?", (cur,))
            cur = (row or {}).get("parent_id")
    return parent_id


async def _check_leader(leader_id: int | None) -> int | None:
    if leader_id is None:
        return None
    if not await fetch_one("SELECT id FROM users WHERE id=?", (leader_id,)):
        raise HTTPException(400, "负责人账号不存在")
    return leader_id


def _clean_permissions(values: list[str]) -> list[str]:
    bad = [v for v in values if v not in PERMISSION_MODULES]
    if bad:
        raise HTTPException(400, "权限项不存在：" + "、".join(bad[:5]))
    return sorted(set(values))


@router.get("")
async def list_users(admin: dict = Depends(admin_user)):
    rows = await fetch_all(
        "SELECT u.id,u.username,u.role,u.disabled,u.allowed_models,u.group_id,u.admin_role_id,"
        "u.daily_token_limit,u.monthly_token_limit,u.created_at,u.last_login_at,u.last_login_ip,"
        "g.name group_name,r.name admin_role_name "
        "FROM users u LEFT JOIN user_groups g ON g.id=u.group_id "
        "LEFT JOIN admin_roles r ON r.id=u.admin_role_id ORDER BY u.id")
    usage_rows = await fetch_all(
        "SELECT user_id,"
        "COALESCE(SUM(CASE WHEN created_at>=? THEN total_tokens ELSE 0 END),0) today_tokens,"
        "COALESCE(SUM(CASE WHEN created_at>=? THEN total_tokens ELSE 0 END),0) month_tokens "
        "FROM requests WHERE user_id IS NOT NULL GROUP BY user_id",
        (_day_start(), _month_start()))
    usage = {int(r["user_id"]): r for r in usage_rows}
    items = []
    for row in rows:
        item = {**row, "allowed_models": _allowed_out(row.get("allowed_models")),
                "daily_token_limit": _limit(row.get("daily_token_limit")),
                "monthly_token_limit": _limit(row.get("monthly_token_limit"))}
        u = usage.get(int(row["id"])) or {}
        item["today_tokens"] = int(u.get("today_tokens") or 0)
        item["month_tokens"] = int(u.get("month_tokens") or 0)
        if not item.get("admin_role_name") and row.get("role") == "admin":
            item["admin_role_name"] = "超级管理员"
        items.append(item)
    return {"items": items}


@router.post("")
async def create_user(body: UserBody, request: Request, admin: dict = Depends(admin_user)):
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "角色只能是 admin 或 user")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    if await fetch_one("SELECT id FROM users WHERE username=?", (body.username.strip(),)):
        raise HTTPException(400, "用户名已存在")
    group_id = await _check_group(body.group_id)
    role_id = await _check_role(body.admin_role_id) if body.role == "admin" else None
    uid = await execute(
        "INSERT INTO users(username,password_hash,role,allowed_models,group_id,admin_role_id,"
        "daily_token_limit,monthly_token_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (body.username.strip(), hash_password(body.password), body.role,
         access.normalize(body.allowed_models), group_id, role_id,
         body.daily_token_limit, body.monthly_token_limit, time.time()))
    await auth_identity.link_identity(uid, "username", body.username, body.username)
    await audit(admin, "user.create", body.username,
                f"role={body.role} group={group_id or '-'} admin_role={role_id or '-'}", ip=client_ip(request))
    return {"ok": True, "id": uid}


@router.patch("/{user_id}")
async def patch_user(user_id: int, body: PatchBody, request: Request, admin: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not row:
        raise HTTPException(404, "用户不存在")
    fields = body.model_dump(exclude_unset=True)
    target_role = fields.get("role", row["role"])
    if target_role not in ("admin", "user"):
        raise HTTPException(400, "角色非法")
    if row["role"] == "admin" and target_role != "admin":
        admins = await fetch_one("SELECT COUNT(*) c FROM users WHERE role='admin' AND disabled=0")
        if admins["c"] <= 1:
            raise HTTPException(400, "至少要保留一个管理员")
    if target_role == "user" and fields.get("admin_role_id") is not None:
        raise HTTPException(400, "普通用户不能绑定管理员角色")

    group_id = row.get("group_id")
    if "group_id" in fields:
        group_id = await _check_group(fields["group_id"])
    admin_role_id = row.get("admin_role_id")
    if "admin_role_id" in fields:
        admin_role_id = await _check_role(fields["admin_role_id"]) if target_role == "admin" else None
    elif target_role != "admin":
        admin_role_id = None

    await execute("UPDATE users SET role=?,group_id=?,admin_role_id=? WHERE id=?",
                  (target_role, group_id, admin_role_id, user_id))
    if body.disabled is not None:
        if user_id == admin["id"] and body.disabled:
            raise HTTPException(400, "不能禁用自己")
        await execute("UPDATE users SET disabled=? WHERE id=?", (1 if body.disabled else 0, user_id))
        if body.disabled:
            await execute("UPDATE api_keys SET revoked=1 WHERE user_id=?", (user_id,))
            await revoke_user_sessions(user_id)
    if body.new_password:
        problem = password_problem(body.new_password)
        if problem:
            raise HTTPException(400, problem)
        await execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(body.new_password), user_id))
        await revoke_user_sessions(user_id)
    if body.allowed_models is not None:
        await execute("UPDATE users SET allowed_models=? WHERE id=?",
                      (access.normalize(body.allowed_models), user_id))
    if body.daily_token_limit is not None:
        await execute("UPDATE users SET daily_token_limit=? WHERE id=?", (body.daily_token_limit, user_id))
    if body.monthly_token_limit is not None:
        await execute("UPDATE users SET monthly_token_limit=? WHERE id=?", (body.monthly_token_limit, user_id))
    await audit(admin, "user.update", row["username"],
                str(fields)[:200], ip=client_ip(request))
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(user_id: int, request: Request, admin: dict = Depends(admin_user)):
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除自己")
    row = await fetch_one("SELECT username,role FROM users WHERE id=?", (user_id,))
    if not row:
        raise HTTPException(404, "用户不存在")
    if row["role"] == "admin":
        admins = await fetch_one("SELECT COUNT(*) c FROM users WHERE role='admin' AND id<>?", (user_id,))
        if admins["c"] == 0:
            raise HTTPException(400, "至少要保留一个管理员")
    await execute("UPDATE api_keys SET revoked=1 WHERE user_id=?", (user_id,))
    await revoke_user_sessions(user_id)
    await execute("UPDATE user_groups SET leader_id=NULL WHERE leader_id=?", (user_id,))
    await execute("DELETE FROM users WHERE id=?", (user_id,))
    await audit(admin, "user.delete", row["username"], ip=client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ 用户组
@router.get("/groups")
async def list_groups(admin: dict = Depends(admin_user)):
    rows = await fetch_all(
        "SELECT g.id,g.name,g.description,g.parent_id,g.leader_id,g.sort,g.created_at,"
        "p.name parent_name,l.username leader_name,COUNT(u.id) members "
        "FROM user_groups g LEFT JOIN user_groups p ON p.id=g.parent_id "
        "LEFT JOIN users l ON l.id=g.leader_id LEFT JOIN users u ON u.group_id=g.id "
        "GROUP BY g.id ORDER BY g.sort,g.id")
    return {"items": rows}


@router.post("/groups")
async def create_group(body: GroupBody, request: Request, admin: dict = Depends(admin_user)):
    name = " ".join(body.name.split())
    if await fetch_one("SELECT id FROM user_groups WHERE name=?", (name,)):
        raise HTTPException(400, "同名用户组已存在")
    parent_id = await _check_parent(body.parent_id)
    leader_id = await _check_leader(body.leader_id)
    gid = await execute(
        "INSERT INTO user_groups(name,description,parent_id,leader_id,sort,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (name, body.description.strip(), parent_id, leader_id, body.sort, time.time()))
    await audit(admin, "group.create", name, f"id={gid} parent={parent_id or '-'}", ip=client_ip(request))
    return {"ok": True, "id": gid}


@router.patch("/groups/{gid}")
async def patch_group(gid: int, body: GroupBody, request: Request, admin: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM user_groups WHERE id=?", (gid,))
    if not row:
        raise HTTPException(404, "用户组不存在")
    name = " ".join(body.name.split())
    if await fetch_one("SELECT id FROM user_groups WHERE name=? AND id<>?", (name, gid)):
        raise HTTPException(400, "同名用户组已存在")
    parent_id = await _check_parent(body.parent_id, gid)
    leader_id = await _check_leader(body.leader_id)
    await execute(
        "UPDATE user_groups SET name=?,description=?,parent_id=?,leader_id=?,sort=? WHERE id=?",
        (name, body.description.strip(), parent_id, leader_id, body.sort, gid))
    await audit(admin, "group.update", name, f"parent={parent_id or '-'} leader={leader_id or '-'}",
                ip=client_ip(request))
    return {"ok": True}


@router.delete("/groups/{gid}")
async def delete_group(gid: int, request: Request, admin: dict = Depends(admin_user)):
    row = await fetch_one("SELECT name FROM user_groups WHERE id=?", (gid,))
    if not row:
        raise HTTPException(404, "用户组不存在")
    await execute("UPDATE users SET group_id=NULL WHERE group_id=?", (gid,))
    await execute("UPDATE user_groups SET parent_id=NULL WHERE parent_id=?", (gid,))
    await execute("DELETE FROM user_groups WHERE id=?", (gid,))
    await audit(admin, "group.delete", row["name"], ip=client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ 管理员角色
@router.get("/roles")
async def list_roles(admin: dict = Depends(admin_user)):
    rows = await fetch_all(
        "SELECT r.id,r.name,r.permissions,r.is_super,r.created_at,COUNT(u.id) members "
        "FROM admin_roles r LEFT JOIN users u ON u.admin_role_id=r.id "
        "GROUP BY r.id ORDER BY r.id")
    return {"items": [_role_out(r) | {"members": r["members"]} for r in rows],
            "modules": [{"key": k, "label": v} for k, v in PERMISSION_MODULES.items()]}


@router.post("/roles")
async def create_role(body: RoleBody, request: Request, admin: dict = Depends(admin_user)):
    name = " ".join(body.name.split())
    perms = _clean_permissions(body.permissions)
    if not perms:
        raise HTTPException(400, "至少勾选一项权限")
    if await fetch_one("SELECT id FROM admin_roles WHERE name=?", (name,)):
        raise HTTPException(400, "同名管理员角色已存在")
    rid = await execute(
        "INSERT INTO admin_roles(name,permissions,is_super,created_at) VALUES(?,?,0,?)",
        (name, json.dumps(perms, ensure_ascii=False), time.time()))
    await audit(admin, "admin_role.create", name, ",".join(perms), ip=client_ip(request))
    return {"ok": True, "id": rid}


@router.patch("/roles/{rid}")
async def patch_role(rid: int, body: RolePatch, request: Request, admin: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM admin_roles WHERE id=?", (rid,))
    if not row:
        raise HTTPException(404, "管理员角色不存在")
    name = row["name"]
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = " ".join((data["name"] or "").split())
        if not name:
            raise HTTPException(400, "角色名称不能为空")
        if await fetch_one("SELECT id FROM admin_roles WHERE name=? AND id<>?", (name, rid)):
            raise HTTPException(400, "同名管理员角色已存在")
        await execute("UPDATE admin_roles SET name=? WHERE id=?", (name, rid))
    if "permissions" in data:
        perms = _clean_permissions(data["permissions"] or [])
        if not perms:
            raise HTTPException(400, "至少勾选一项权限")
        await execute("UPDATE admin_roles SET permissions=? WHERE id=?",
                      (json.dumps(perms, ensure_ascii=False), rid))
    await audit(admin, "admin_role.update", name, str(data)[:200], ip=client_ip(request))
    return {"ok": True}


@router.delete("/roles/{rid}")
async def delete_role(rid: int, request: Request, admin: dict = Depends(admin_user)):
    row = await fetch_one("SELECT name FROM admin_roles WHERE id=?", (rid,))
    if not row:
        raise HTTPException(404, "管理员角色不存在")
    members = await fetch_one("SELECT COUNT(*) c FROM users WHERE admin_role_id=?", (rid,))
    if (members or {}).get("c", 0):
        raise HTTPException(400, "还有管理员绑定该角色，请先在用户页移除")
    await execute("DELETE FROM admin_roles WHERE id=?", (rid,))
    await audit(admin, "admin_role.delete", row["name"], ip=client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ 导入 / 导出
_IMPORT_ALIASES = {
    "username": "username", "用户名": "username", "账号": "username",
    "password": "password", "密码": "password",
    "role": "role", "角色": "role",
    "group": "group", "用户组": "group", "部门": "group",
    "allowed_models": "models", "可用模型": "models", "模型": "models",
    "daily_token_limit": "daily", "每日配额": "daily", "日配额": "daily",
    "monthly_token_limit": "monthly", "每月配额": "monthly", "月配额": "monthly",
    "admin_role": "admin_role", "管理员角色": "admin_role",
    "disabled": "disabled", "禁用": "disabled",
}


def _csv_value(row: list[str], indexes: dict[str, int], key: str, fallback: int,
               default: str = "") -> str:
    idx = indexes.get(key)
    if idx is not None and idx < len(row):
        return (row[idx] or "").strip()
    if fallback < len(row):
        return (row[fallback] or "").strip()
    return default


@router.post("/import")
async def import_users(body: ImportBody, request: Request, admin: dict = Depends(admin_user)):
    default_group = await _check_group(body.default_group_id)
    if body.default_role not in ("admin", "user"):
        raise HTTPException(400, "默认角色只能是 admin 或 user")
    text = (body.text or "").replace("\r\n", "\n").replace("\r", "\n")
    rows = list(csv.reader(io.StringIO(text)))
    header_indexes: dict[str, int] = {}
    start = 0
    if rows and rows[0]:
        first = (rows[0][0] or "").strip().lower()
        if first in _IMPORT_ALIASES:
            for i, h in enumerate(rows[0]):
                key = _IMPORT_ALIASES.get((h or "").strip().lower())
                if key:
                    header_indexes[key] = i
            start = 1
    created, skipped, errors = 0, 0, []
    for line_no, row in enumerate(rows[start:], start + 1):
        if not row or not any((x or "").strip() for x in row):
            continue
        username = _csv_value(row, header_indexes, "username", 0)
        password = _csv_value(row, header_indexes, "password", 1)
        role = _csv_value(row, header_indexes, "role", 2, body.default_role) or body.default_role
        group_name = _csv_value(row, header_indexes, "group", 3)
        models_raw = _csv_value(row, header_indexes, "models", 4)
        daily_raw = _csv_value(row, header_indexes, "daily", 5, str(body.default_daily_token_limit))
        monthly_raw = _csv_value(row, header_indexes, "monthly", 6, str(body.default_monthly_token_limit))
        admin_role_name = _csv_value(row, header_indexes, "admin_role", 7)
        disabled_raw = _csv_value(row, header_indexes, "disabled", 99, "0")
        try:
            if len(username) < 2 or len(username) > 32:
                raise ValueError("用户名需要 2–32 位")
            problem = password_problem(password)
            if problem:
                raise ValueError(problem)
            if role not in ("admin", "user"):
                raise ValueError("角色只能是 admin 或 user")
            admin_role_id = None
            if admin_role_name:
                if role != "admin":
                    raise ValueError("普通用户不能绑定管理员角色")
                r = await fetch_one("SELECT id FROM admin_roles WHERE name=?", (admin_role_name,))
                if not r:
                    raise ValueError(f"管理员角色不存在：{admin_role_name}")
                admin_role_id = r["id"]
            group_id = default_group
            if group_name:
                g = await fetch_one("SELECT id FROM user_groups WHERE name=?", (group_name,))
                if not g:
                    raise ValueError(f"用户组不存在：{group_name}")
                group_id = g["id"]
            models = [m.strip() for m in (models_raw or "").replace("；", ",")
                      .replace("，", ",").replace(";", ",").split(",") if m.strip()]
            if not models:
                models = ["*"]
            disabled = 1 if (disabled_raw or "").strip().lower() in (
                "1", "true", "yes", "y", "是", "禁用") else 0
            daily = int(daily_raw or 0)
            monthly = int(monthly_raw or 0)
            if daily < 0 or monthly < 0:
                raise ValueError("配额不能为负数")
            if await fetch_one("SELECT id FROM users WHERE username=?", (username,)):
                skipped += 1
                continue
            uid = await execute(
                "INSERT INTO users(username,password_hash,role,allowed_models,group_id,admin_role_id,"
                "daily_token_limit,monthly_token_limit,disabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (username, hash_password(password), role, access.normalize(models), group_id,
                 admin_role_id, daily, monthly, disabled, time.time()))
            await auth_identity.link_identity(uid, "username", username, username)
            created += 1
        except Exception as exc:
            errors.append({"line": line_no, "error": str(exc)})
    await audit(admin, "user.import", detail=f"created={created} skipped={skipped} errors={len(errors)}",
                ip=client_ip(request))
    return {"created": created, "skipped": skipped, "errors": errors}


@router.get("/export")
async def export_users(admin: dict = Depends(admin_user)):
    rows = await fetch_all(
        "SELECT u.username,u.role,u.disabled,u.allowed_models,u.daily_token_limit,"
        "u.monthly_token_limit,u.created_at,u.last_login_at,g.name group_name,r.name admin_role_name "
        "FROM users u LEFT JOIN user_groups g ON g.id=u.group_id "
        "LEFT JOIN admin_roles r ON r.id=u.admin_role_id ORDER BY u.id")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["username", "role", "group", "admin_role", "disabled", "allowed_models",
                     "daily_token_limit", "monthly_token_limit", "created_at", "last_login_at"])
    for r in rows:
        models = _allowed_out(r.get("allowed_models"))
        models_text = ",".join(models) if isinstance(models, list) else models
        writer.writerow([r["username"], r["role"], r.get("group_name") or "", r.get("admin_role_name") or "",
                         "1" if r.get("disabled") else "0", models_text,
                         r.get("daily_token_limit") or 0, r.get("monthly_token_limit") or 0,
                         r.get("created_at") or "", r.get("last_login_at") or ""])
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="workbench-users.csv"'})


# ------------------------------------------------------------------ 会话# ------------------------------------------------------------------ 会话
@router.get("/sessions")
async def sessions(admin: dict = Depends(admin_user)):
    rows = await fetch_all(
        "SELECT s.id,s.user_id,u.username,s.created_at,s.expires_at,s.ip,s.ua,s.revoked "
        "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.revoked=0 ORDER BY s.created_at DESC LIMIT 100")
    return {"items": rows}


@router.delete("/sessions/{sid}")
async def kill_session(sid: int, request: Request, admin: dict = Depends(admin_user)):
    await revoke_user_sessions_by_id(sid)
    await audit(admin, "session.revoke", str(sid), ip=client_ip(request))
    return {"ok": True}


async def revoke_user_sessions_by_id(sid: int) -> None:
    await execute("UPDATE sessions SET revoked=1 WHERE id=?", (sid,))

