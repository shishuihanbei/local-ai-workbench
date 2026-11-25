"""协作套件：智能体、小队、公告、服务台和对话分享。"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

from ..db import execute, fetch_all, fetch_one

AGENT_VISIBILITIES = {"public", "squad", "private"}
SQUAD_ROLES = {"owner", "member"}
TICKET_STATUSES = {"open", "processing", "resolved", "closed"}
TICKET_PRIORITIES = {"low", "normal", "high"}
ANNOUNCEMENT_LEVELS = {"info", "warning", "important"}


def new_share_token() -> str:
    return secrets.token_urlsafe(18)


async def visible_agents(user: dict[str, Any]) -> list[dict[str, Any]]:
    """普通用户可见：公开智能体 + 自己的 + 自己小队绑定的。"""
    rows = await fetch_all(
        "SELECT a.*,(SELECT u.username FROM users u WHERE u.id=a.owner_id) owner_name "
        "FROM agents a WHERE a.enabled=1 AND (a.visibility='public' OR a.owner_id=? "
        "OR a.id IN (SELECT sa.agent_id FROM squad_agents sa JOIN squad_members sm "
        "ON sm.squad_id=sa.squad_id WHERE sm.user_id=?)) "
        "ORDER BY a.sort, a.id", (user["id"], user["id"]))
    return rows


async def agent_for_chat(agent_id: int, user: dict[str, Any]) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM agents WHERE id=? AND enabled=1", (agent_id,))
    if not row:
        return None
    if row["visibility"] == "public" or row["owner_id"] == user["id"]:
        return row
    joined = await fetch_one(
        "SELECT 1 FROM squad_agents sa JOIN squad_members sm ON sm.squad_id=sa.squad_id "
        "WHERE sa.agent_id=? AND sm.user_id=?", (agent_id, user["id"]))
    return row if joined else None


async def squad_for_user(squad_id: int, user: dict[str, Any], *, allow_admin: bool = True) -> dict[str, Any] | None:
    row = await fetch_one("SELECT * FROM squads WHERE id=?", (squad_id,))
    if not row:
        return None
    if row["owner_id"] == user["id"] or (allow_admin and user.get("role") == "admin"):
        return row
    joined = await fetch_one(
        "SELECT 1 FROM squad_members WHERE squad_id=? AND user_id=?", (squad_id, user["id"]))
    return row if joined else None


async def squad_detail(squad_id: int, user: dict[str, Any], *, allow_admin: bool = True) -> dict[str, Any] | None:
    squad = await squad_for_user(squad_id, user, allow_admin=allow_admin)
    if not squad:
        return None
    owner = await fetch_one("SELECT username FROM users WHERE id=?", (squad["owner_id"],)) or {}
    members = await fetch_all(
        "SELECT sm.user_id,sm.role,sm.joined_at,u.username,u.role user_role,u.group_id,"
        "(SELECT g.name FROM user_groups g WHERE g.id=u.group_id) group_name "
        "FROM squad_members sm JOIN users u ON u.id=sm.user_id WHERE sm.squad_id=? "
        "ORDER BY CASE sm.role WHEN 'owner' THEN 0 ELSE 1 END, u.username", (squad_id,))
    agents = await fetch_all(
        "SELECT a.id,a.name,a.avatar,a.description,a.visibility,a.enabled "
        "FROM squad_agents sa JOIN agents a ON a.id=sa.agent_id WHERE sa.squad_id=? "
        "ORDER BY a.sort, a.id", (squad_id,))
    conversations = await fetch_all(
        "SELECT sc.conversation_id,sc.shared_by,sc.created_at,c.title,c.model,"
        "(SELECT u.username FROM users u WHERE u.id=sc.shared_by) shared_by_name "
        "FROM squad_conversations sc JOIN conversations c ON c.id=sc.conversation_id "
        "WHERE sc.squad_id=? ORDER BY sc.created_at DESC", (squad_id,))
    return {
        **squad, "owner_name": owner.get("username", ""),
        "members": members, "agents": agents, "conversations": conversations,
        "member_count": len(members), "agent_count": len(agents),
        "conversation_count": len(conversations),
    }


async def my_squads(user: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT s.*,(SELECT u.username FROM users u WHERE u.id=s.owner_id) owner_name,"
        "(SELECT COUNT(*) FROM squad_members sm WHERE sm.squad_id=s.id) member_count,"
        "(SELECT COUNT(*) FROM squad_agents sa WHERE sa.squad_id=s.id) agent_count,"
        "(SELECT COUNT(*) FROM squad_conversations sc WHERE sc.squad_id=s.id) conversation_count,"
        "(SELECT role FROM squad_members sm WHERE sm.squad_id=s.id AND sm.user_id=?) my_role "
        "FROM squads s WHERE s.owner_id=? OR s.id IN "
        "(SELECT squad_id FROM squad_members WHERE user_id=?) "
        "ORDER BY s.updated_at DESC", (user["id"], user["id"], user["id"]))
    return rows


async def ticket_detail(ticket_id: int, user: dict[str, Any], *, allow_admin: bool = True) -> dict[str, Any] | None:
    ticket = await fetch_one("SELECT * FROM tickets WHERE id=?", (ticket_id,))
    if not ticket:
        return None
    if ticket["user_id"] != user["id"] and not (allow_admin and user.get("role") == "admin"):
        return None
    messages = await fetch_all(
        "SELECT id,user_id,username,role,content,created_at FROM ticket_messages "
        "WHERE ticket_id=? ORDER BY id", (ticket_id,))
    return {**ticket, "messages": messages}


async def create_ticket(*, user: dict[str, Any], title: str, content: str,
                        category: str, priority: str) -> dict[str, Any]:
    now = time.time()
    tid = await execute(
        "INSERT INTO tickets(user_id,username,title,content,category,priority,status,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (user["id"], user.get("username", ""), title, content, category, priority,
         "open", now, now))
    await execute(
        "INSERT INTO ticket_messages(ticket_id,user_id,username,role,content,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (tid, user["id"], user.get("username", ""), "user", content, now))
    return await ticket_detail(tid, user) or {}


async def share_conversation(*, conversation_id: int, user: dict[str, Any], visibility: str,
                             squad_id: int | None, expires_days: int) -> dict[str, Any] | None:
    conv = await fetch_one(
        "SELECT id,title,user_id,model FROM conversations WHERE id=?", (conversation_id,))
    if not conv or conv["user_id"] != user["id"]:
        return None
    if visibility not in ("public", "squad"):
        visibility = "public"
    if visibility == "squad":
        if not squad_id or not await squad_for_user(int(squad_id), user):
            return None
    rows = await fetch_all(
        "SELECT role,content,created_at FROM messages WHERE conversation_id=? "
        "ORDER BY id", (conversation_id,))
    snapshot = [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
                for r in rows if r["role"] in ("user", "assistant") and (r["content"] or "").strip()]
    now = time.time()
    expires_at = now + max(1, min(int(expires_days), 365)) * 86400 if expires_days else None
    token = new_share_token()
    sid = await execute(
        "INSERT INTO conversation_shares(conversation_id,owner_id,owner_name,title,token,"
        "visibility,squad_id,snapshot,expires_at,view_count,enabled,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (conversation_id, user["id"], user.get("username", ""), conv["title"] or "未命名对话",
         token, visibility, squad_id if visibility == "squad" else None,
         json.dumps(snapshot, ensure_ascii=False), expires_at, 0, 1, now))
    return {
        "id": sid, "token": token, "title": conv["title"] or "未命名对话",
        "visibility": visibility, "squad_id": squad_id if visibility == "squad" else None,
        "expires_at": expires_at, "message_count": len(snapshot),
        "url": f"/share/{token}",
    }


async def read_share(token: str, user: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = await fetch_one("SELECT * FROM conversation_shares WHERE token=? AND enabled=1", (token,))
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < time.time():
        return None
    if row["visibility"] == "squad":
        if not user:
            return None
        if not await squad_for_user(int(row["squad_id"] or 0), user):
            return None
    await execute("UPDATE conversation_shares SET view_count=view_count+1 WHERE id=?", (row["id"],))
    try:
        messages = json.loads(row["snapshot"] or "[]")
    except Exception:
        messages = []
    return {"title": row["title"], "owner_name": row["owner_name"], "visibility": row["visibility"],
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "messages": messages, "view_count": int(row["view_count"] or 0) + 1}


async def list_partners() -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT u.id,u.username,u.role,u.disabled,u.last_login_at,u.group_id,"
        "(SELECT g.name FROM user_groups g WHERE g.id=u.group_id) group_name,"
        "u.admin_role_id,(SELECT r.name FROM admin_roles r WHERE r.id=u.admin_role_id) admin_role_name,"
        "(SELECT COUNT(*) FROM squad_members sm WHERE sm.user_id=u.id) squad_count "
        "FROM users u ORDER BY u.username")
