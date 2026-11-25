"""长期记忆：抽取规则、开关、管理接口与上下文注入。"""
from __future__ import annotations

import asyncio

from backend.services import memory


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_extract_only_stable_self_statements():
    assert memory.extract_candidates("我叫张三，是一名前端工程师。") == ["我叫张三，是一名前端工程师"]
    assert memory.extract_candidates("我喜欢用 NAS 存资料。") == ["我喜欢用 NAS 存资料"]
    assert memory.extract_candidates("以后都用中文回答。") == ["以后都用中文回答"]
    assert memory.extract_candidates("记住：我的项目在 D 盘。") == ["我的项目在 D 盘"]
    assert memory.extract_candidates("你记住我的喜好吗？") == []
    assert memory.extract_candidates("今天天气怎么样？") == []
    assert memory.extract_candidates("你叫什么名字？") == []


def test_extract_skips_secrets():
    assert memory.extract_candidates("我的密码是 abc123。") == []


def test_memory_off_returns_empty_context():
    from backend.config import load_config, save_config

    cfg = load_config()
    old = cfg.get("memory_enabled")
    cfg["memory_enabled"] = False
    save_config(cfg)
    try:
        data = asyncio.run(memory.context(1, "我叫什么"))
        assert data == {"enabled": False, "items": [], "prompt": ""}
    finally:
        cfg["memory_enabled"] = bool(old)
        save_config(cfg)


def test_memory_admin_toggle_and_crud(client, admin_token):
    h = auth(admin_token)
    r = client.get("/api/admin/memory", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    uid = body["current_user_id"]

    assert client.post("/api/admin/memory/toggle", headers=h, json={"enabled": True}).status_code == 200
    try:
        r = client.post("/api/admin/memory/items", headers=h,
                        json={"content": "我叫测试管理员，常用 Windows。", "user_id": uid})
        assert r.status_code == 200, r.text
        mid = r.json()["item"]["id"]
        rows = client.get("/api/admin/memory", headers=h).json()
        assert rows["enabled"] is True
        assert any(x["id"] == mid and x["source"] == "manual" for x in rows["items"])
        assert rows["stats"]["total"] >= 1

        r = client.patch(f"/api/admin/memory/items/{mid}", headers=h,
                         json={"content": "我叫测试管理员，常用 Windows 和 NAS。"})
        assert r.status_code == 200, r.text
        assert "NAS" in r.json()["item"]["content"]

        assert client.delete(f"/api/admin/memory/items/{mid}", headers=h).status_code == 200
        assert client.delete(f"/api/admin/memory/items/{mid}", headers=h).status_code == 404
    finally:
        client.post("/api/admin/memory/toggle", headers=h, json={"enabled": False})


def test_chat_context_includes_memory_when_enabled(monkeypatch):
    from backend.routers.chat import ChatBody, _build_context

    async def fake_context(user_id: int, query: str = ""):
        return {"enabled": True, "items": [{"id": 7, "kind": "fact", "content": "用户叫张三"}],
                "prompt": "长期记忆：用户叫张三"}

    monkeypatch.setattr(memory, "context", fake_context)
    body = ChatBody(message="我叫什么", use_kb=False)
    msgs, _, meta = asyncio.run(_build_context({"id": 1}, body, {"system_prompt": "", "kb_enabled": False}, att_rows=[]))
    assert "长期记忆：用户叫张三" in msgs[0]["content"]
    assert meta["memory"]["count"] == 1
    assert meta["memory"]["ids"] == [7]
