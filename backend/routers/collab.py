"""协作 API：智能体、伙伴、小队、公告、服务台和对话分享。"""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db import audit, execute, fetch_all, fetch_one
from ..security import (SESSION_COOKIE, admin_user, current_user, session_user,
                        user_from_any_token)
from ..services import collab

admin_router = APIRouter(prefix="/api/admin", tags=["collab-admin"])
router = APIRouter(prefix="/api", tags=["collab"])


async def optional_user(request: Request) -> dict[str, Any] | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = await user_from_any_token(auth.split(" ", 1)[1].strip())
        if user:
            return user
    return await session_user(request.cookies.get(SESSION_COOKIE))


def _text(value: str, *, limit: int, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(400, f"{label}不能为空")
    if len(value) > limit:
        raise HTTPException(400, f"{label}不能超过 {limit} 字")
    return value


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    avatar: str = Field(default="🤖", max_length=8)
    system_prompt: str = Field(default="", max_length=4000)
    model: str = Field(default="", max_length=120)
    visibility: str = Field(default="public", max_length=20)
    enabled: bool = True
    sort: int = 0


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    avatar: str | None = Field(default=None, max_length=8)
    system_prompt: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=120)
    visibility: str | None = Field(default=None, max_length=20)
    enabled: bool | None = None
    sort: int | None = None


class SquadBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    owner_id: int | None = None


class SquadPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)


class MemberBody(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    role: str = Field(default="member", max_length=20)


class SquadAgentBody(BaseModel):
    agent_id: int


class AnnouncementBody(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=4000)
    level: str = Field(default="info", max_length=20)
    pinned: bool = False
    enabled: bool = True


class AnnouncementPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    level: str | None = Field(default=None, max_length=20)
    pinned: bool | None = None
    enabled: bool | None = None


class TicketCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="other", max_length=30)
    priority: str = Field(default="normal", max_length=20)


class TicketPatch(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    assignee_id: int | None = None
    priority: str | None = Field(default=None, max_length=20)


class TicketReply(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ShareBody(BaseModel):
    visibility: str = Field(default="public", max_length=20)
    squad_id: int | None = None
    expires_days: int = Field(default=0, ge=0, le=365)


def _check_visibility(value: str) -> str:
    if value not in collab.AGENT_VISIBILITIES:
        raise HTTPException(400, "可见范围只能是 public、squad 或 private")
    return value


def _check_level(value: str) -> str:
    if value not in collab.ANNOUNCEMENT_LEVELS:
        raise HTTPException(400, "公告级别只能是 info、warning 或 important")
    return value


def _check_ticket_status(value: str) -> str:
    if value not in collab.TICKET_STATUSES:
        raise HTTPException(400, "工单状态只能是 open、processing、resolved 或 closed")
    return value


def _check_priority(value: str) -> str:
    if value not in collab.TICKET_PRIORITIES:
        raise HTTPException(400, "优先级只能是 low、normal 或 high")
    return value


# ------------------------------------------------------------------ 智能体
@admin_router.get("/agents")
async def admin_agents(q: str = "", user: dict = Depends(admin_user)):
    where: str = ""
    args: list[Any] = []
    if q.strip():
        where, args = (" WHERE a.name LIKE ? OR a.description LIKE ?", [f"%{q.strip()}%"] * 2)
    rows = await fetch_all(
        f"SELECT a.*,(SELECT u.username FROM users u WHERE u.id=a.owner_id) owner_name "
        f"FROM agents a{where} ORDER BY a.sort,a.id", tuple(args))
    return {"items": rows}


@admin_router.post("/agents")
async def create_agent(body: AgentBody, user: dict = Depends(admin_user)):
    name = _text(body.name, limit=60, label="智能体名称")
    visibility = _check_visibility(body.visibility)
    if await fetch_one("SELECT id FROM agents WHERE LOWER(name)=LOWER(?)", (name,)):
        raise HTTPException(400, "这个智能体名称已经存在")
    now = time.time()
    aid = await execute(
        "INSERT INTO agents(name,description,avatar,system_prompt,model,visibility,owner_id,"
        "enabled,sort,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (name, body.description.strip(), body.avatar.strip() or "🤖",
         body.system_prompt.strip(), body.model.strip(), visibility, user["id"],
         1 if body.enabled else 0, int(body.sort), now, now))
    await audit(user, "agent.create", name, f"visibility={visibility}")
    return {"ok": True, "id": aid}


@admin_router.patch("/agents/{aid}")
async def patch_agent(aid: int, body: AgentPatch, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM agents WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "智能体不存在")
    values: dict[str, Any] = {}
    for key, value in body.model_dump(exclude_none=True).items():
        if key == "visibility":
            values[key] = _check_visibility(value)
        elif key == "name":
            name = _text(value, limit=60, label="智能体名称")
            dup = await fetch_one("SELECT id FROM agents WHERE LOWER(name)=LOWER(?) AND id<>?", (name, aid))
            if dup:
                raise HTTPException(400, "这个智能体名称已经存在")
            values[key] = name
        elif key in ("description", "avatar", "system_prompt", "model"):
            values[key] = (value or "").strip()
        elif key in ("enabled",):
            values[key] = 1 if value else 0
        elif key == "sort":
            values[key] = int(value)
    if values:
        values["updated_at"] = time.time()
        sets = ",".join(f"{k}=?" for k in values)
        await execute(f"UPDATE agents SET {sets} WHERE id=?", tuple(values.values()) + (aid,))
    await audit(user, "agent.update", values.get("name", row["name"]))
    return {"ok": True}


@admin_router.delete("/agents/{aid}")
async def delete_agent(aid: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT name FROM agents WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "智能体不存在")
    await execute("DELETE FROM agents WHERE id=?", (aid,))
    await audit(user, "agent.delete", row["name"])
    return {"ok": True}


# ------------------------------------------------------------------ 伙伴
@admin_router.get("/partners")
async def partners(q: str = "", user: dict = Depends(admin_user)):
    rows = await collab.list_partners()
    if q.strip():
        q = q.strip().lower()
        rows = [r for r in rows if q in (r["username"] or "").lower()
                or q in (r.get("group_name") or "").lower()
                or q in (r.get("admin_role_name") or "").lower()]
    return {"items": rows}


# ------------------------------------------------------------------ 小队
async def _admin_squad_rows() -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT s.*,(SELECT u.username FROM users u WHERE u.id=s.owner_id) owner_name,"
        "(SELECT COUNT(*) FROM squad_members sm WHERE sm.squad_id=s.id) member_count,"
        "(SELECT COUNT(*) FROM squad_agents sa WHERE sa.squad_id=s.id) agent_count,"
        "(SELECT COUNT(*) FROM squad_conversations sc WHERE sc.squad_id=s.id) conversation_count "
        "FROM squads s ORDER BY s.updated_at DESC")


@admin_router.get("/squads")
async def admin_squads(user: dict = Depends(admin_user)):
    return {"items": await _admin_squad_rows()}


@admin_router.post("/squads")
async def create_squad(body: SquadBody, user: dict = Depends(admin_user)):
    name = _text(body.name, limit=60, label="小队名称")
    if await fetch_one("SELECT id FROM squads WHERE LOWER(name)=LOWER(?)", (name,)):
        raise HTTPException(400, "这个小队名称已经存在")
    owner_id = int(body.owner_id or user["id"])
    owner = await fetch_one("SELECT id,username FROM users WHERE id=?", (owner_id,))
    if not owner:
        raise HTTPException(400, "小队所有者不存在")
    now = time.time()
    sid = await execute(
        "INSERT INTO squads(name,description,owner_id,created_at,updated_at) VALUES(?,?,?,?,?)",
        (name, body.description.strip(), owner_id, now, now))
    await execute("INSERT OR IGNORE INTO squad_members(squad_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                  (sid, owner_id, "owner", now))
    await audit(user, "squad.create", name, f"owner={owner['username']}")
    return {"ok": True, "id": sid}


@admin_router.get("/squads/{sid}")
async def admin_squad_detail(sid: int, user: dict = Depends(admin_user)):
    data = await collab.squad_detail(sid, user)
    if not data:
        raise HTTPException(404, "小队不存在")
    return data


@admin_router.patch("/squads/{sid}")
async def patch_squad(sid: int, body: SquadPatch, user: dict = Depends(admin_user)):
    values = {k: (v or "").strip() for k, v in body.model_dump(exclude_none=True).items()}
    if "name" in values:
        name = _text(values["name"], limit=60, label="小队名称")
        dup = await fetch_one("SELECT id FROM squads WHERE LOWER(name)=LOWER(?) AND id<>?", (name, sid))
        if dup:
            raise HTTPException(400, "这个小队名称已经存在")
        values["name"] = name
    if values:
        values["updated_at"] = time.time()
        sets = ",".join(f"{k}=?" for k in values)
        await execute(f"UPDATE squads SET {sets} WHERE id=?", tuple(values.values()) + (sid,))
    return {"ok": True}


@admin_router.delete("/squads/{sid}")
async def delete_squad(sid: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT name FROM squads WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "小队不存在")
    await execute("DELETE FROM squads WHERE id=?", (sid,))
    await audit(user, "squad.delete", row["name"])
    return {"ok": True}


@admin_router.post("/squads/{sid}/members")
async def admin_add_member(sid: int, body: MemberBody, user: dict = Depends(admin_user)):
    return await _add_squad_member(sid, body, user)


@admin_router.delete("/squads/{sid}/members/{uid}")
async def admin_remove_member(sid: int, uid: int, user: dict = Depends(admin_user)):
    return await _remove_squad_member(sid, uid, user)


@admin_router.post("/squads/{sid}/agents")
async def admin_add_squad_agent(sid: int, body: SquadAgentBody, user: dict = Depends(admin_user)):
    return await _add_squad_agent(sid, body, user)


@admin_router.delete("/squads/{sid}/agents/{aid}")
async def admin_remove_squad_agent(sid: int, aid: int, user: dict = Depends(admin_user)):
    await execute("DELETE FROM squad_agents WHERE squad_id=? AND agent_id=?", (sid, aid))
    return {"ok": True}


async def _require_squad(sid: int, user: dict, *, allow_admin: bool = True) -> dict[str, Any]:
    squad = await collab.squad_for_user(sid, user, allow_admin=allow_admin)
    if not squad:
        raise HTTPException(404, "小队不存在或你不在这个小组")
    return squad


async def _add_squad_member(sid: int, body: MemberBody, user: dict) -> dict[str, Any]:
    await _require_squad(sid, user)
    target = await fetch_one("SELECT id,username FROM users WHERE username=?", (body.username.strip(),))
    if not target:
        raise HTTPException(404, "找不到这个用户")
    if body.role not in collab.SQUAD_ROLES:
        raise HTTPException(400, "成员角色只能是 owner 或 member")
    await execute(
        "INSERT OR REPLACE INTO squad_members(squad_id,user_id,role,joined_at) VALUES(?,?,?,?)",
        (sid, target["id"], body.role, time.time()))
    await execute("UPDATE squads SET updated_at=? WHERE id=?", (time.time(), sid))
    return {"ok": True, "user_id": target["id"], "username": target["username"]}


async def _remove_squad_member(sid: int, uid: int, user: dict) -> dict[str, Any]:
    squad = await _require_squad(sid, user)
    if int(uid) == int(squad["owner_id"]):
        raise HTTPException(400, "不能移除小队所有者，请先转移或删除小队")
    await execute("DELETE FROM squad_members WHERE squad_id=? AND user_id=?", (sid, uid))
    return {"ok": True}


async def _add_squad_agent(sid: int, body: SquadAgentBody, user: dict) -> dict[str, Any]:
    await _require_squad(sid, user)
    agent = await fetch_one("SELECT id,name FROM agents WHERE id=?", (body.agent_id,))
    if not agent:
        raise HTTPException(404, "智能体不存在")
    await execute("INSERT OR IGNORE INTO squad_agents(squad_id,agent_id,added_at) VALUES(?,?,?)",
                  (sid, body.agent_id, time.time()))
    return {"ok": True}


# ------------------------------------------------------------------ 公告
@admin_router.get("/announcements")
async def admin_announcements(q: str = "", user: dict = Depends(admin_user)):
    where, args = ("", [])
    if q.strip():
        where, args = (" WHERE title LIKE ? OR content LIKE ?", [f"%{q.strip()}%"] * 2)
    rows = await fetch_all(
        f"SELECT a.*,(SELECT u.username FROM users u WHERE u.id=a.created_by) creator_name "
        f"FROM announcements a{where} ORDER BY a.pinned DESC,a.created_at DESC", tuple(args))
    return {"items": rows}


@admin_router.post("/announcements")
async def create_announcement(body: AnnouncementBody, user: dict = Depends(admin_user)):
    title = _text(body.title, limit=100, label="公告标题")
    content = _text(body.content, limit=4000, label="公告内容")
    level = _check_level(body.level)
    now = time.time()
    aid = await execute(
        "INSERT INTO announcements(title,content,level,pinned,enabled,created_by,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (title, content, level, 1 if body.pinned else 0, 1 if body.enabled else 0,
         user["id"], now, now))
    await audit(user, "announcement.create", title)
    return {"ok": True, "id": aid}


@admin_router.patch("/announcements/{aid}")
async def patch_announcement(aid: int, body: AnnouncementPatch, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT title FROM announcements WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "公告不存在")
    values: dict[str, Any] = {}
    for key, value in body.model_dump(exclude_none=True).items():
        if key == "level":
            values[key] = _check_level(value)
        elif key in ("title", "content"):
            values[key] = _text(value, limit=100 if key == "title" else 4000,
                                label="公告标题" if key == "title" else "公告内容")
        elif key in ("pinned", "enabled"):
            values[key] = 1 if value else 0
    if values:
        values["updated_at"] = time.time()
        sets = ",".join(f"{k}=?" for k in values)
        await execute(f"UPDATE announcements SET {sets} WHERE id=?", tuple(values.values()) + (aid,))
    return {"ok": True}


@admin_router.delete("/announcements/{aid}")
async def delete_announcement(aid: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT title FROM announcements WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "公告不存在")
    await execute("DELETE FROM announcements WHERE id=?", (aid,))
    await audit(user, "announcement.delete", row["title"])
    return {"ok": True}


# ------------------------------------------------------------------ 服务台
@admin_router.get("/tickets")
async def admin_tickets(status: str = "", priority: str = "", q: str = "",
                        limit: int = Query(100, ge=1, le=300), user: dict = Depends(admin_user)):
    where, args = ["1=1"], []
    if status in collab.TICKET_STATUSES:
        where.append("status=?")
        args.append(status)
    if priority in collab.TICKET_PRIORITIES:
        where.append("priority=?")
        args.append(priority)
    if q.strip():
        where.append("(title LIKE ? OR content LIKE ? OR username LIKE ?)")
        args += [f"%{q.strip()}%"] * 3
    rows = await fetch_all(
        f"SELECT * FROM tickets WHERE {' AND '.join(where)} ORDER BY "
        "CASE status WHEN 'open' THEN 0 WHEN 'processing' THEN 1 ELSE 2 END, "
        "CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, updated_at DESC LIMIT ?",
        tuple(args) + (limit,))
    return {"items": rows, "stats": {
        "open": await _ticket_count("open"), "processing": await _ticket_count("processing"),
        "resolved": await _ticket_count("resolved"), "closed": await _ticket_count("closed")}}


async def _ticket_count(status: str) -> int:
    row = await fetch_one("SELECT COUNT(*) c FROM tickets WHERE status=?", (status,)) or {}
    return int(row.get("c") or 0)


@admin_router.get("/tickets/{tid}")
async def admin_ticket_detail(tid: int, user: dict = Depends(admin_user)):
    data = await collab.ticket_detail(tid, user)
    if not data:
        raise HTTPException(404, "工单不存在")
    return data


@admin_router.patch("/tickets/{tid}")
async def patch_ticket(tid: int, body: TicketPatch, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM tickets WHERE id=?", (tid,))
    if not row:
        raise HTTPException(404, "工单不存在")
    values: dict[str, Any] = {}
    if body.status is not None:
        values["status"] = _check_ticket_status(body.status)
    if body.priority is not None:
        values["priority"] = _check_priority(body.priority)
    if body.assignee_id is not None:
        assignee = await fetch_one("SELECT id,username FROM users WHERE id=?", (body.assignee_id,))
        if not assignee:
            raise HTTPException(400, "指派的管理员不存在")
        values["assignee_id"] = assignee["id"]
        values["assignee_name"] = assignee["username"]
    if values:
        values["updated_at"] = time.time()
        sets = ",".join(f"{k}=?" for k in values)
        await execute(f"UPDATE tickets SET {sets} WHERE id=?", tuple(values.values()) + (tid,))
    await audit(user, "ticket.update", row["title"], str(values))
    return {"ok": True}


@admin_router.post("/tickets/{tid}/reply")
async def admin_reply_ticket(tid: int, body: TicketReply, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT title,status FROM tickets WHERE id=?", (tid,))
    if not row:
        raise HTTPException(404, "工单不存在")
    now = time.time()
    await execute(
        "INSERT INTO ticket_messages(ticket_id,user_id,username,role,content,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (tid, user["id"], user.get("username", ""), "staff", body.content.strip(), now))
    await execute(
        "UPDATE tickets SET status=CASE WHEN status='open' THEN 'processing' ELSE status END,"
        "assignee_id=COALESCE(assignee_id,?),assignee_name=CASE WHEN assignee_name='' THEN ? "
        "ELSE assignee_name END,last_reply_at=?,updated_at=? WHERE id=?",
        (user["id"], user.get("username", ""), now, now, tid))
    return {"ok": True}


@admin_router.get("/shares")
async def admin_shares(limit: int = Query(100, ge=1, le=300), user: dict = Depends(admin_user)):
    rows = await fetch_all(
        "SELECT cs.*,cs.view_count,(SELECT COUNT(*) FROM json_each(cs.snapshot)) message_count "
        "FROM conversation_shares cs ORDER BY cs.created_at DESC LIMIT ?", (limit,))
    return {"items": rows}


@admin_router.delete("/shares/{share_id}")
async def admin_delete_share(share_id: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT title FROM conversation_shares WHERE id=?", (share_id,))
    if not row:
        raise HTTPException(404, "分享不存在")
    await execute("DELETE FROM conversation_shares WHERE id=?", (share_id,))
    await audit(user, "share.delete", row["title"])
    return {"ok": True}


# ------------------------------------------------------------------ 用户端
@router.get("/agents")
async def my_agents(user: dict = Depends(current_user)):
    return {"items": await collab.visible_agents(user)}


@router.get("/squads")
async def list_my_squads(user: dict = Depends(current_user)):
    return {"items": await collab.my_squads(user)}


@router.post("/squads")
async def create_my_squad(body: SquadBody, user: dict = Depends(current_user)):
    name = _text(body.name, limit=60, label="小队名称")
    if await fetch_one("SELECT id FROM squads WHERE LOWER(name)=LOWER(?)", (name,)):
        raise HTTPException(400, "这个小队名称已经存在")
    now = time.time()
    sid = await execute(
        "INSERT INTO squads(name,description,owner_id,created_at,updated_at) VALUES(?,?,?,?,?)",
        (name, body.description.strip(), user["id"], now, now))
    await execute("INSERT OR IGNORE INTO squad_members(squad_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                  (sid, user["id"], "owner", now))
    return {"ok": True, "id": sid}


@router.get("/squads/{sid}")
async def my_squad_detail(sid: int, user: dict = Depends(current_user)):
    data = await collab.squad_detail(sid, user)
    if not data:
        raise HTTPException(404, "小队不存在或你不在这个小组")
    return data


@router.patch("/squads/{sid}")
async def patch_my_squad(sid: int, body: SquadPatch, user: dict = Depends(current_user)):
    squad = await _require_squad(sid, user, allow_admin=False)
    if squad["owner_id"] != user["id"]:
        raise HTTPException(403, "只有小队长可以修改小队")
    values = {k: (v or "").strip() for k, v in body.model_dump(exclude_none=True).items()}
    if values:
        values["updated_at"] = time.time()
        sets = ",".join(f"{k}=?" for k in values)
        await execute(f"UPDATE squads SET {sets} WHERE id=?", tuple(values.values()) + (sid,))
    return {"ok": True}


@router.delete("/squads/{sid}")
async def delete_my_squad(sid: int, user: dict = Depends(current_user)):
    squad = await _require_squad(sid, user, allow_admin=False)
    if squad["owner_id"] != user["id"]:
        raise HTTPException(403, "只有小队长可以删除小队")
    await execute("DELETE FROM squads WHERE id=?", (sid,))
    return {"ok": True}


@router.post("/squads/{sid}/members")
async def add_my_squad_member(sid: int, body: MemberBody, user: dict = Depends(current_user)):
    squad = await _require_squad(sid, user, allow_admin=False)
    if squad["owner_id"] != user["id"]:
        raise HTTPException(403, "只有小队长可以添加成员")
    return await _add_squad_member(sid, body, user)


@router.delete("/squads/{sid}/members/{uid}")
async def remove_my_squad_member(sid: int, uid: int, user: dict = Depends(current_user)):
    squad = await _require_squad(sid, user, allow_admin=False)
    if squad["owner_id"] != user["id"]:
        raise HTTPException(403, "只有小队长可以移除成员")
    return await _remove_squad_member(sid, uid, user)


@router.post("/squads/{sid}/agents")
async def add_my_squad_agent(sid: int, body: SquadAgentBody, user: dict = Depends(current_user)):
    squad = await _require_squad(sid, user, allow_admin=False)
    if squad["owner_id"] != user["id"]:
        raise HTTPException(403, "只有小队长可以绑定智能体")
    return await _add_squad_agent(sid, body, user)


@router.delete("/squads/{sid}/agents/{aid}")
async def remove_my_squad_agent(sid: int, aid: int, user: dict = Depends(current_user)):
    squad = await _require_squad(sid, user, allow_admin=False)
    if squad["owner_id"] != user["id"]:
        raise HTTPException(403, "只有小队长可以解绑智能体")
    await execute("DELETE FROM squad_agents WHERE squad_id=? AND agent_id=?", (sid, aid))
    return {"ok": True}


@router.post("/squads/{sid}/conversations")
async def share_to_squad(sid: int, body: dict, user: dict = Depends(current_user)):
    await _require_squad(sid, user, allow_admin=False)
    cid = int(body.get("conversation_id") or 0)
    conv = await fetch_one("SELECT id FROM conversations WHERE id=? AND user_id=?", (cid, user["id"]))
    if not conv:
        raise HTTPException(404, "只能共享自己的对话")
    await execute("INSERT OR IGNORE INTO squad_conversations(squad_id,conversation_id,shared_by,created_at) "
                  "VALUES(?,?,?,?)", (sid, cid, user["id"], time.time()))
    await execute("UPDATE squads SET updated_at=? WHERE id=?", (time.time(), sid))
    return {"ok": True}


@router.get("/squads/{sid}/conversations/{cid}")
async def read_squad_conversation(sid: int, cid: int, user: dict = Depends(current_user)):
    await _require_squad(sid, user)
    shared = await fetch_one(
        "SELECT 1 FROM squad_conversations WHERE squad_id=? AND conversation_id=?", (sid, cid))
    if not shared:
        raise HTTPException(404, "这段对话还没有共享到小队")
    conv = await fetch_one("SELECT id,title,model,created_at,updated_at FROM conversations WHERE id=?", (cid,))
    messages = await fetch_all(
        "SELECT role,content,created_at FROM messages WHERE conversation_id=? AND role IN ('user','assistant') "
        "ORDER BY id", (cid,))
    return {"conversation": conv, "messages": messages}


@router.get("/announcements")
async def my_announcements(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT a.*,(SELECT u.username FROM users u WHERE u.id=a.created_by) creator_name "
        "FROM announcements a WHERE a.enabled=1 ORDER BY a.pinned DESC,a.created_at DESC LIMIT 10")
    return {"items": rows}


@router.get("/tickets")
async def my_tickets(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT * FROM tickets WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (user["id"],))
    return {"items": rows}


@router.post("/tickets")
async def create_my_ticket(body: TicketCreate, user: dict = Depends(current_user)):
    return await collab.create_ticket(
        user=user, title=_text(body.title, limit=120, label="工单标题"),
        content=_text(body.content, limit=4000, label="问题描述"),
        category=body.category.strip() or "other", priority=_check_priority(body.priority))


@router.get("/tickets/{tid}")
async def my_ticket_detail(tid: int, user: dict = Depends(current_user)):
    data = await collab.ticket_detail(tid, user, allow_admin=False)
    if not data:
        raise HTTPException(404, "工单不存在")
    return data


@router.post("/tickets/{tid}/reply")
async def my_ticket_reply(tid: int, body: TicketReply, user: dict = Depends(current_user)):
    data = await collab.ticket_detail(tid, user, allow_admin=False)
    if not data:
        raise HTTPException(404, "工单不存在")
    now = time.time()
    await execute(
        "INSERT INTO ticket_messages(ticket_id,user_id,username,role,content,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (tid, user["id"], user.get("username", ""), "user", body.content.strip(), now))
    await execute("UPDATE tickets SET status=CASE WHEN status='closed' THEN 'open' ELSE status END,"
                  "updated_at=? WHERE id=?", (now, tid))
    return {"ok": True}


@router.post("/conversations/{cid}/share")
async def create_share(cid: int, body: ShareBody, user: dict = Depends(current_user)):
    share = await collab.share_conversation(
        conversation_id=cid, user=user, visibility=body.visibility,
        squad_id=body.squad_id, expires_days=body.expires_days)
    if not share:
        raise HTTPException(400, "无法分享：请确认对话属于你，且小队分享已选择自己的小队")
    return share


@router.get("/shares")
async def my_shares(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT * FROM conversation_shares WHERE owner_id=? ORDER BY created_at DESC LIMIT 100",
        (user["id"],))
    return {"items": rows}


@router.delete("/shares/{share_id}")
async def delete_my_share(share_id: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT owner_id,title FROM conversation_shares WHERE id=?", (share_id,))
    if not row:
        raise HTTPException(404, "分享不存在")
    if row["owner_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(403, "只能撤销自己的分享")
    await execute("DELETE FROM conversation_shares WHERE id=?", (share_id,))
    return {"ok": True}


@router.get("/shares/{token}")
async def read_share(token: str, request: Request):
    user = await optional_user(request)
    data = await collab.read_share(token, user)
    if not data:
        raise HTTPException(404, "分享不存在、已失效或无权访问")
    return data
