"""云端补强：敏感判定、复杂度打分、配置接口与审计预算。"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from conftest import auth


def test_sensitivity_and_complexity():
    from backend.services import assist

    cfg = {"assist_sensitive_words": ""}
    assert "手机号" in assist.sensitivity("他的手机号是 13800138000", cfg)
    assert "身份证" in assist.sensitivity("身份证 110101199001011234", cfg)
    assert assist.sensitivity("帮我写一份周报，主题是项目进度", cfg) == ""
    assert "薪酬" in assist.sensitivity("整理一下本月薪酬表", cfg)
    assert "自定义" in assist.sensitivity("这里有自定义机密", {"assist_sensitive_words": "自定义"})

    assert assist.complexity("你好", "", 0) == 0
    assert assist.complexity("先查资料再写报告，最后做对比", "docx", 0) >= 3
    assert assist.complexity("字" * 1200, "", 0) >= 2
    assert assist.complexity("短问题", "", 3) >= 1
    # 估算与预算口径一致：chars//2 + 256
    assert assist.estimate_tokens("a" * 100) == 306
    assert assist.estimate_tokens("") == 256


def test_assist_config_requires_cloud_provider(client: TestClient, admin_token):
    h = auth(admin_token)
    r = client.post("/api/admin/providers", headers=h, json={
        "name": "doubao-test", "kind": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key": "sk-test", "models": "doubao-pro-32k", "price_in": 0.1,
        "price_out": 0.2, "enabled": True,
    })
    assert r.status_code == 200, r.text
    items = client.get("/api/admin/providers", headers=h).json()["items"]
    pid = next(p["id"] for p in items if p["name"] == "doubao-test")

    before = client.get("/api/admin/assist", headers=h).json()
    assert before["providers"]

    bad = client.put("/api/admin/assist", headers=h, json={
        "enabled": True, "provider_id": 9999, "model": "",
    })
    assert bad.status_code == 404

    ok = client.put("/api/admin/assist", headers=h, json={
        "enabled": True, "provider_id": pid, "model": "", "auto_threshold": 4,
        "daily_tokens": 150000, "allow_attachments": False, "open_to_all": True,
        "sensitive_words": "",
    })
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["active"] and data["active_model"] == "doubao-pro-32k"

    got = client.get("/api/admin/assist", headers=h).json()
    assert got["enabled"] and got["provider_id"] == pid
    assert got["active"] and got["active_provider"] == "doubao-test"

    # 关闭后 target 为空，功能自动休眠
    off = client.put("/api/admin/assist", headers=h, json={
        "enabled": False, "provider_id": 0, "model": "", "auto_threshold": 4,
        "daily_tokens": 150000,
    })
    assert off.status_code == 200 and off.json()["active"] is False


async def _budget_case():
    from backend.db import execute, fetch_one
    from backend.services import assist

    user = await fetch_one("SELECT id FROM users ORDER BY id LIMIT 1")
    uid = int(user["id"])
    cfg = {"assist_daily_tokens": 600}
    await execute("DELETE FROM assist_logs WHERE user_id=?", (uid,))
    assert await assist.budget_ok(uid, 100, cfg)
    await assist.log(user_id=uid, provider="mock", model="m", reason="测试",
                     tokens_in=200, tokens_out=200)
    assert await assist.used_today(uid) == 400
    assert await assist.budget_ok(uid, 100, cfg) is False
    await assist.log(user_id=uid, provider="mock", model="m", reason="测试2",
                     tokens_in=10, tokens_out=10)
    rows = await fetch_one("SELECT COUNT(*) n FROM assist_logs WHERE user_id=?", (uid,))
    assert int(rows["n"]) >= 2


def test_budget_and_audit_log(client: TestClient):
    asyncio.run(_budget_case())


def test_deep_mode_blocks_sensitive_before_cloud(client: TestClient, admin_token):
    r = client.post("/api/chat/stream", headers=auth(admin_token), json={
        "message": "我的手机号是 13800138000，记到通讯录",
        "assist_reason": "用户开启深度模式",
    })
    assert r.status_code == 403, r.text


def test_direct_cloud_model_respects_sensitive_and_budget(client: TestClient, admin_token):
    """用户直接选云端模型时，也要过敏感词与每日预算，不能绕过补强护栏。"""
    h = auth(admin_token)
    r = client.post("/api/admin/providers", headers=h, json={
        "name": "doubao-direct", "kind": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key": "sk-test", "models": "doubao-direct-32k", "enabled": True,
    })
    assert r.status_code == 200, r.text
    pid = next(p["id"] for p in client.get("/api/admin/providers", headers=h).json()["items"]
               if p["name"] == "doubao-direct")
    ok = client.put("/api/admin/assist", headers=h, json={
        "enabled": True, "provider_id": pid, "model": "doubao-direct-32k",
        "auto_threshold": 4, "daily_tokens": 1, "open_to_all": True,
    })
    assert ok.status_code == 200, ok.text

    blocked = client.post("/api/chat/stream", headers=h, json={
        "message": "我的身份证号是 110101199001011234，帮我核对",
        "model": "doubao-direct-32k",
    })
    assert blocked.status_code == 403, blocked.text

    limited = client.post("/api/chat/stream", headers=h, json={
        "message": "你好，介绍一下这份周报模板", "model": "doubao-direct-32k",
    })
    assert limited.status_code == 429, limited.text

    off = client.put("/api/admin/assist", headers=h, json={
        "enabled": False, "provider_id": 0, "model": "", "auto_threshold": 4,
        "daily_tokens": 150000,
    })
    assert off.status_code == 200


def test_task_runs_have_route_columns(client: TestClient):
    from backend.db import fetch_all

    async def check():
        cols = await fetch_all("PRAGMA table_info(task_runs)")
        names = {c["name"] for c in cols}
        assert {"route", "route_reason"} <= names
        tables = await fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        assert "assist_logs" in {t["name"] for t in tables}

    asyncio.run(check())
