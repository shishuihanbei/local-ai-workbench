"""协作套件：智能体、小队、公告、服务台和对话分享。"""
from __future__ import annotations

import asyncio

from backend.db import execute, fetch_all, fetch_one


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_agent_crud_and_visibility(client, admin_token):
    r = client.post("/api/admin/agents", headers=auth(admin_token), json={
        "name": "测试审查员", "description": "检查代码风险", "avatar": "🧪",
        "system_prompt": "你是严谨的审查员。", "model": "", "visibility": "public",
        "enabled": True, "sort": 3,
    })
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    rows = client.get("/api/admin/agents", headers=auth(admin_token)).json()["items"]
    assert any(a["id"] == aid and a["name"] == "测试审查员" for a in rows)
    mine = client.get("/api/agents", headers=auth(admin_token)).json()["items"]
    assert any(a["id"] == aid for a in mine)
    r = client.patch(f"/api/admin/agents/{aid}", headers=auth(admin_token),
                     json={"visibility": "private", "enabled": False})
    assert r.status_code == 200, r.text
    mine = client.get("/api/agents", headers=auth(admin_token)).json()["items"]
    assert not any(a["id"] == aid for a in mine)
    assert client.delete(f"/api/admin/agents/{aid}", headers=auth(admin_token)).status_code == 200


def test_squad_members_agents_and_conversations(client, admin_token):
    a = client.post("/api/admin/agents", headers=auth(admin_token), json={
        "name": "小队助手", "system_prompt": "你是小队助手。", "visibility": "squad",
    }).json()["id"]
    r = client.post("/api/admin/squads", headers=auth(admin_token),
                    json={"name": "测试小队", "description": "协作测试"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/admin/squads/{sid}/members", headers=auth(admin_token),
                       json={"username": "admin", "role": "member"}).status_code == 200
    assert client.post(f"/api/admin/squads/{sid}/agents", headers=auth(admin_token),
                       json={"agent_id": a}).status_code == 200
    detail = client.get(f"/api/admin/squads/{sid}", headers=auth(admin_token)).json()
    assert detail["member_count"] >= 1
    assert detail["agent_count"] == 1

    cid = client.post("/api/chat/conversations", headers=auth(admin_token),
                      json={"title": "小队共享测试"}).json()["id"]
    asyncio.run(execute("INSERT INTO messages(conversation_id,role,content,tokens,created_at) "
                        "VALUES(?,?,?,?,?)", (cid, "user", "共享消息", 2, 1.0)))
    r = client.post(f"/api/squads/{sid}/conversations", headers=auth(admin_token),
                    json={"conversation_id": cid})
    assert r.status_code == 200, r.text
    shared = client.get(f"/api/squads/{sid}/conversations/{cid}", headers=auth(admin_token))
    assert shared.status_code == 200
    assert any(m["content"] == "共享消息" for m in shared.json()["messages"])

    assert client.delete(f"/api/admin/squads/{sid}", headers=auth(admin_token)).status_code == 200
    client.delete(f"/api/admin/agents/{a}", headers=auth(admin_token))


def test_announcements_and_partners(client, admin_token):
    r = client.post("/api/admin/announcements", headers=auth(admin_token), json={
        "title": "测试公告", "content": "今晚维护。", "level": "warning",
        "pinned": True, "enabled": True,
    })
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    items = client.get("/api/announcements", headers=auth(admin_token)).json()["items"]
    assert any(a["id"] == aid and a["pinned"] == 1 for a in items)
    assert client.patch(f"/api/admin/announcements/{aid}", headers=auth(admin_token),
                        json={"enabled": False}).status_code == 200
    items = client.get("/api/announcements", headers=auth(admin_token)).json()["items"]
    assert not any(a["id"] == aid for a in items)
    assert client.delete(f"/api/admin/announcements/{aid}", headers=auth(admin_token)).status_code == 200

    partners = client.get("/api/admin/partners", headers=auth(admin_token)).json()["items"]
    assert any(p["username"] == "admin" for p in partners)
    assert "squad_count" in partners[0]


def test_ticket_flow(client, admin_token):
    r = client.post("/api/tickets", headers=auth(admin_token), json={
        "title": "测试工单", "content": "模型没有返回结果。", "priority": "high",
    })
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    mine = client.get("/api/tickets", headers=auth(admin_token)).json()["items"]
    assert any(t["id"] == tid for t in mine)
    r = client.post(f"/api/admin/tickets/{tid}/reply", headers=auth(admin_token),
                    json={"content": "已收到，正在排查。"})
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/admin/tickets/{tid}", headers=auth(admin_token)).json()
    assert detail["status"] == "processing"
    assert len(detail["messages"]) == 2
    r = client.patch(f"/api/admin/tickets/{tid}", headers=auth(admin_token),
                     json={"status": "resolved"})
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/tickets/{tid}", headers=auth(admin_token)).json()
    assert detail["status"] == "resolved"
    assert client.post(f"/api/tickets/{tid}/reply", headers=auth(admin_token),
                       json={"content": "问题已处理。"}).status_code == 200


def test_conversation_share_snapshot_and_revoke(client, admin_token):
    cid = client.post("/api/chat/conversations", headers=auth(admin_token),
                      json={"title": "分享测试对话"}).json()["id"]
    asyncio.run(execute("INSERT INTO messages(conversation_id,role,content,tokens,created_at) "
                        "VALUES(?,?,?,?,?)", (cid, "user", "分享前的问题", 3, 1.0)))
    r = client.post(f"/api/conversations/{cid}/share", headers=auth(admin_token),
                    json={"visibility": "public", "expires_days": 1})
    assert r.status_code == 200, r.text
    share = r.json()
    assert share["message_count"] == 1
    public = client.get(f"/api/shares/{share['token']}")
    assert public.status_code == 200
    data = public.json()
    assert data["title"] == "分享测试对话"
    assert data["messages"][0]["content"] == "分享前的问题"
    admin_list = client.get("/api/admin/shares", headers=auth(admin_token))
    assert admin_list.status_code == 200
    assert any(s["token"] == share["token"] for s in admin_list.json()["items"])

    # 快照不会因为后续消息而变化
    asyncio.run(execute("INSERT INTO messages(conversation_id,role,content,tokens,created_at) "
                        "VALUES(?,?,?,?,?)", (cid, "assistant", "分享后的回答", 3, 2.0)))
    assert client.get(f"/api/shares/{share['token']}").json()["messages"] == data["messages"]

    mine = client.get("/api/shares", headers=auth(admin_token)).json()["items"]
    assert any(s["token"] == share["token"] for s in mine)
    assert client.delete(f"/api/admin/shares/{share['id']}", headers=auth(admin_token)).status_code == 200
    assert client.get(f"/api/shares/{share['token']}").status_code == 404


def test_collaboration_tables_and_permissions(admin_token):
    async def check():
        tables = await fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        names = {t["name"] for t in tables}
        assert {"agents", "squads", "squad_members", "squad_agents", "squad_conversations",
                "announcements", "tickets", "ticket_messages", "conversation_shares"} <= names
        row = await fetch_one("SELECT version,name FROM schema_migrations ORDER BY version DESC LIMIT 1")
        assert row["version"] == 24 and row["name"] == "task_agent_fields"
    asyncio.run(check())
    from backend.security import PERMISSION_MODULES
    assert {"agents", "partners", "squads", "announcements", "tickets", "conv_shares"} <= set(PERMISSION_MODULES)


