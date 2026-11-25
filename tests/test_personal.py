"""个人知识库与用户自助记忆：权限隔离和开关生效。"""
from __future__ import annotations

import time

from backend.config import load_config, save_config


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _make_user(client, admin_token: str, name: str) -> str:
    h = auth(admin_token)
    r = client.post("/api/users", headers=h, json={
        "username": name, "password": "Pytest-pass-2026", "role": "user"})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={
        "username": name, "password": "Pytest-pass-2026"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_my_kb_switch_and_sources_default_off(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok = _make_user(client, admin_token, f"kbsw{suffix}")
    cfg = load_config()
    old = cfg.get("kb_enabled")
    cfg["kb_enabled"] = False
    save_config(cfg)
    try:
        d = client.get("/api/my/kb", headers=auth(tok)).json()
        assert d["public_enabled"] is False
        assert d["personal_enabled"] is False
        assert d["use_public"] is False
        assert d["use_personal"] is True

        r = client.post("/api/my/kb/settings", headers=auth(tok),
                        json={"personal_enabled": True})
        assert r.status_code == 200, r.text
        assert r.json()["personal_enabled"] is True
        assert r.json()["use_personal"] is True

        r = client.post("/api/my/kb/settings", headers=auth(tok),
                        json={"use_public": True})
        assert r.status_code == 200
        assert r.json()["use_public"] is True

        r = client.post("/api/my/kb/settings", headers=auth(tok),
                        json={"use_personal": False})
        assert r.status_code == 200
        assert r.json()["use_personal"] is False
    finally:
        cfg["kb_enabled"] = bool(old)
        save_config(cfg)


def test_chat_uses_personal_kb_only_after_user_enables_it(client, admin_token):
    import asyncio
    from backend.config import load_config, save_config
    from backend.routers.chat import ChatBody, _build_context

    suffix = str(int(time.time()))[-6:]
    tok = _make_user(client, admin_token, f"kbchat{suffix}")
    me = client.get("/api/auth/me", headers=auth(tok)).json()
    uid = me["user"]["id"]
    r = client.post("/api/my/kb/text", headers=auth(tok),
                    data={"title": "退款时效", "content": "退款在三个工作日内原路退回。"})
    assert r.status_code == 200, r.text

    cfg = load_config()
    old = cfg.get("kb_enabled")
    cfg["kb_enabled"] = False
    save_config(cfg)
    chat_cfg = {"system_prompt": "", "kb_enabled": False, "kb_top_k": 3}
    body = ChatBody(message="退款几天", use_kb=True)
    try:
        _, _, meta = asyncio.run(_build_context({"id": uid}, body, chat_cfg, att_rows=[]))
        assert "kb" not in meta
        assert client.post("/api/my/kb/settings", headers=auth(tok),
                           json={"personal_enabled": True}).status_code == 200
        _, _, meta = asyncio.run(_build_context({"id": uid}, body, chat_cfg, att_rows=[]))
        assert "退款时效" in (meta.get("kb") or [])
    finally:
        cfg["kb_enabled"] = bool(old)
        save_config(cfg)


def test_admin_kb_backup_keeps_personal_scope(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok = _make_user(client, admin_token, f"kbe{suffix}")
    r = client.post("/api/my/kb/text", headers=auth(tok),
                    data={"title": "个人备份文档", "content": "这条个人资料需要按原账号恢复。"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    r = client.get("/api/kb/export", headers=auth(admin_token))
    assert r.status_code == 200
    payload = r.json()
    item = next((x for x in payload["docs"] if x["title"] == "个人备份文档"), None)
    assert item and item["scope"] == "personal" and item["username"]
    assert client.delete(f"/api/kb/{doc_id}", headers=auth(admin_token)).status_code == 200
    r = client.post("/api/kb/restore", headers=auth(admin_token),
                    files={"file": ("kb.json", r.content, "application/json")})
    assert r.status_code == 200, r.text
    rows = client.get("/api/my/kb", headers=auth(tok)).json()
    assert any(d["title"] == "个人备份文档" for d in rows["docs"])


def test_admin_only_public_kb(client, admin_token):
    h = auth(admin_token)
    r = client.post("/api/kb/text", headers=h,
                    data={"title": "公共资料", "content": "公共知识库只允许管理员写入。"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert r.json()["scope"] == "global"
    overview = client.get("/api/kb", headers=h).json()
    assert overview["count"] >= 1
    assert any(d["id"] == doc_id for d in overview["docs"])
    hits = client.get("/api/kb/search", headers=h, params={"q": "公共知识库"}).json()["items"]
    assert any(x["doc_id"] == doc_id for x in hits)
    assert client.delete(f"/api/kb/{doc_id}", headers=h).status_code == 200


def test_personal_kb_is_isolated_from_public_and_other_users(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok_a = _make_user(client, admin_token, f"kba{suffix}")
    tok_b = _make_user(client, admin_token, f"kbb{suffix}")

    # 普通用户不能写公共库
    r = client.post("/api/kb/text", headers=auth(tok_a),
                    data={"title": "越权公共", "content": "不应写入公共库"})
    assert r.status_code == 403, r.text

    r = client.post("/api/my/kb/text", headers=auth(tok_a),
                    data={"title": "个人退款规则", "content": "退款在 3 个工作日内原路退回。"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert r.json()["scope"] == "personal"

    mine = client.get("/api/my/kb", headers=auth(tok_a)).json()
    assert mine["count"] == 1 and mine["docs"][0]["title"] == "个人退款规则"

    # 自己的检索能命中，别人看不到；管理员能在全部库里看到并管理
    assert client.get("/api/my/kb/search", headers=auth(tok_a),
                      params={"q": "退款几天"}).json()["items"]
    assert client.get("/api/my/kb/search", headers=auth(tok_b),
                      params={"q": "退款几天"}).json()["items"] == []
    admin_all = client.get("/api/kb", headers=auth(admin_token),
                           params={"scope": "all"}).json()
    row = next((d for d in admin_all["docs"] if d["id"] == doc_id), None)
    assert row and row["scope"] == "personal" and row["username"]
    admin_public = client.get("/api/kb", headers=auth(admin_token),
                              params={"scope": "global"}).json()
    assert all(d["id"] != doc_id for d in admin_public["docs"])
    admin_hits = client.get("/api/kb/search", headers=auth(admin_token),
                            params={"q": "退款几天"}).json()["items"]
    assert any(x["doc_id"] == doc_id and x["scope"] == "personal" for x in admin_hits)

    # 别人不能删除，本人可以
    assert client.delete(f"/api/my/kb/{doc_id}", headers=auth(tok_b)).status_code == 404
    assert client.delete(f"/api/my/kb/{doc_id}", headers=auth(tok_a)).status_code == 200
    assert client.get("/api/my/kb", headers=auth(tok_a)).json()["count"] == 0


def test_admin_can_delete_personal_kb(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok = _make_user(client, admin_token, f"kbd{suffix}")
    r = client.post("/api/my/kb/text", headers=auth(tok),
                    data={"title": "管理员待删", "content": "管理员应该能删除用户个人文档。"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    detail = client.get(f"/api/kb/doc/{doc_id}", headers=auth(admin_token)).json()
    assert detail["scope"] == "personal" and detail["username"]
    assert "管理员应该能删除" in detail["content"]
    assert client.get(f"/api/kb/doc/{doc_id}", headers=auth(tok)).status_code == 403
    assert client.delete(f"/api/kb/{doc_id}", headers=auth(admin_token)).status_code == 200
    assert client.get("/api/my/kb", headers=auth(tok)).json()["count"] == 0


def test_personal_kb_export_and_rename(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok = _make_user(client, admin_token, f"kbc{suffix}")
    r = client.post("/api/my/kb/text", headers=auth(tok),
                    data={"title": "旧标题", "content": "个人资料正文，用来验证导出。"})
    doc_id = r.json()["id"]
    r = client.patch(f"/api/my/kb/{doc_id}", headers=auth(tok),
                     data={"title": "新标题"})
    assert r.status_code == 200, r.text
    rows = client.get("/api/my/kb", headers=auth(tok)).json()["docs"]
    assert rows[0]["title"] == "新标题"
    r = client.get("/api/my/kb/export", headers=auth(tok))
    assert r.status_code == 200
    assert "个人资料正文" in r.text


def test_user_memory_requires_both_switches(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok = _make_user(client, admin_token, f"mem{suffix}")
    h = auth(tok)
    cfg = load_config()
    old = cfg.get("memory_enabled")
    cfg["memory_enabled"] = False
    save_config(cfg)
    try:
        r = client.get("/api/my/memory", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["global_enabled"] is False

        r = client.post("/api/my/memory/toggle", headers=h, json={"enabled": True})
        assert r.status_code == 200, r.text
        assert r.json()["user_enabled"] is True
        assert r.json()["effective"] is False

        r = client.post("/api/admin/memory/toggle", headers=auth(admin_token),
                        json={"enabled": True})
        assert r.status_code == 200

        status = client.get("/api/my/memory", headers=h).json()
        assert status["effective"] is True

        r = client.post("/api/my/memory/items", headers=h,
                        json={"content": "我叫个人用户，常用 Windows。"})
        assert r.status_code == 200, r.text
        mid = r.json()["item"]["id"]
        assert client.get("/api/my/memory", headers=h).json()["stats"]["total"] >= 1

        tok_b = _make_user(client, admin_token, f"memx{suffix}")
        assert client.delete(f"/api/my/memory/items/{mid}",
                             headers=auth(tok_b)).status_code == 404

        assert client.post("/api/my/memory/clear", headers=h, json={}).status_code == 200
        assert client.get("/api/my/memory", headers=h).json()["stats"]["total"] == 0
    finally:
        cfg = load_config()
        cfg["memory_enabled"] = bool(old)
        save_config(cfg)
