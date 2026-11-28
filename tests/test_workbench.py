"""工作台与定时任务：迁移、计划计算、CRUD。"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

from conftest import auth


def test_migration_creates_task_tables(client, admin_token):
    from backend.db import fetch_all, fetch_one

    async def check():
        tables = await fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        names = {t["name"] for t in tables}
        assert {"scheduled_tasks", "task_runs", "workbench_active"} <= names
        row = await fetch_one(
            "SELECT version,name FROM schema_migrations ORDER BY version DESC LIMIT 1")
        assert row["version"] == 24 and row["name"] == "task_agent_fields"

    asyncio.run(check())


def test_next_run_calculation():
    from backend.services import scheduler

    base = datetime(2026, 11, 24, 10, 0).timestamp()  # 周二
    daily = scheduler.next_run({"frequency": "daily", "time_of_day": "09:00"}, after=base)
    assert datetime.fromtimestamp(daily).strftime("%Y-%m-%d %H:%M") == "2026-11-25 09:00"

    weekly = scheduler.next_run(
        {"frequency": "weekly", "time_of_day": "09:00", "weekdays": "1"}, after=base)
    assert datetime.fromtimestamp(weekly).strftime("%Y-%m-%d %H:%M") == "2026-11-30 09:00"

    monthly = scheduler.next_run(
        {"frequency": "monthly", "time_of_day": "09:00", "day_of_month": 15}, after=base)
    assert datetime.fromtimestamp(monthly).strftime("%Y-%m-%d %H:%M") == "2026-12-15 09:00"

    once = scheduler.next_run(
        {"frequency": "once", "run_at": base + 3600}, after=base)
    assert once == base + 3600
    assert scheduler.next_run({"frequency": "once", "run_at": base - 10}, after=base) is None


def test_workbench_task_crud(client, admin_token):
    from backend.db import fetch_one

    run_at = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    payload = {
        "title": "每天早上生成简报",
        "prompt": "整理今天的 AI 行业动态，输出 5 条，带来源链接。",
        "frequency": "once",
        "run_at": run_at,
        "time_of_day": "09:00",
        "weekdays": [1],
        "day_of_month": 1,
        "model": "1.5b",
        "output_format": "docx",
        "web_enabled": True,
        "enabled": True,
    }
    r = client.post("/api/workbench/tasks", json=payload, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["title"] == payload["title"]
    assert task["output_format"] == "docx"
    assert task["web_enabled"] is True
    assert task["schedule"].startswith("一次性")
    assert task["next_run_at"]

    r = client.get("/api/workbench/tasks", headers=auth(admin_token))
    assert r.status_code == 200
    assert any(x["id"] == task["id"] for x in r.json()["items"])

    r = client.patch(f"/api/workbench/tasks/{task['id']}", json={"enabled": False},
                     headers=auth(admin_token))
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    payload2 = dict(payload, frequency="daily", run_at=None)
    r = client.put(f"/api/workbench/tasks/{task['id']}", json=payload2,
                   headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["frequency"] == "daily"
    assert r.json()["next_run_at"]

    r = client.get("/api/workbench/overview", headers=auth(admin_token))
    assert r.status_code == 200
    assert "counts" in r.json() and "upcoming" in r.json()

    r = client.delete(f"/api/workbench/tasks/{task['id']}", headers=auth(admin_token))
    assert r.status_code == 200
    row = asyncio.run(fetch_one("SELECT id FROM scheduled_tasks WHERE id=?", (task["id"],)))
    assert row is None


def test_workbench_task_validation(client, admin_token):
    r = client.post("/api/workbench/tasks", json={
        "title": "过去时间", "prompt": "测试", "frequency": "once",
        "run_at": (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"),
    }, headers=auth(admin_token))
    assert r.status_code == 400

    r = client.post("/api/workbench/tasks", json={
        "title": "缺少时间", "prompt": "测试", "frequency": "once",
    }, headers=auth(admin_token))
    assert r.status_code == 400


def test_workbench_template_accepts_eight_quick(client, admin_token):
    payload = {
        "name": "八项推荐工作台",
        "icon": "🎓",
        "description": "首页展示八个推荐任务。",
        "quick": [
            {"label": f"任务{i}", "text": f"执行第 {i} 个推荐任务。", "format": ""}
            for i in range(1, 9)
        ],
        "skill_id": "plan",
        "skills": ["plan"],
        "plugins": ["docgen"],
    }
    r = client.post("/api/workbench/templates", json=payload, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    tpl = r.json()
    assert len(tpl["quick"]) == 8
    assert tpl["quick"][-1]["label"] == "任务8"
    r = client.delete(f"/api/workbench/templates/{tpl['id']}", headers=auth(admin_token))
    assert r.status_code == 200


def test_workbench_custom_template_and_share(client, admin_token):
    from backend.db import execute, fetch_one

    payload = {
        "name": "内容运营工作台",
        "icon": "✍️",
        "description": "选题、脚本和复盘放在一起。",
        "quick": [
            {"label": "选题", "text": "围绕账号定位给 10 个选题。", "format": ""},
            {"label": "脚本", "text": "把选题写成 45 秒短视频脚本。", "format": "docx"},
        ],
        "skill_id": "polish",
        "skills": ["polish", "plan", "summary"],
        "plugins": ["web", "docgen"],
    }
    r = client.post("/api/workbench/templates", json=payload, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    tpl = r.json()
    assert tpl["name"] == payload["name"]
    assert tpl["quick"][1]["format"] == "docx"
    assert tpl["skill_id"] == "polish" and tpl["skill_name"] == "润色改写"
    assert tpl["skills"] == ["polish", "plan", "summary"]
    assert tpl["skill_names"] == ["润色改写", "方案规划", "总结提炼"]
    assert tpl["plugins"] == ["docgen", "web"]

    r = client.get("/api/workbench/templates", headers=auth(admin_token))
    assert r.status_code == 200
    assert any(x["id"] == tpl["id"] for x in r.json()["items"])

    r = client.put(f"/api/workbench/templates/{tpl['id']}", json={
        **payload, "name": "内容运营工作台 2.0",
    }, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "内容运营工作台 2.0"

    r = client.post("/api/workbench/shares", json={
        **payload, "expires_days": 30,
    }, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    share = r.json()
    assert share["url"] == f"/wb/{share['token']}"

    r = client.get(f"/api/workbench/shares/{share['token']}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == payload["name"]
    assert data["quick"][0]["label"] == "选题"
    assert data["skill_id"] == "polish" and data["skill_name"] == "润色改写"
    assert data["skills"] == ["polish", "plan", "summary"]
    assert data["plugins"] == ["docgen", "web"]
    assert data["view_count"] >= 1

    r = client.post("/api/workbench/templates", json={
        **payload, "plugins": ["not-a-plugin"],
    }, headers=auth(admin_token))
    assert r.status_code == 400

    asyncio.run(execute(
        "UPDATE workbench_shares SET expires_at=? WHERE token=?",
        (time.time() - 5, share["token"])))
    r = client.get(f"/api/workbench/shares/{share['token']}")
    assert r.status_code == 404

    asyncio.run(execute("DELETE FROM workbench_shares WHERE token=?", (share["token"],)))
    r = client.delete(f"/api/workbench/templates/{tpl['id']}", headers=auth(admin_token))
    assert r.status_code == 200
    assert asyncio.run(fetch_one(
        "SELECT id FROM workbench_templates WHERE id=?", (tpl["id"],))) is None


def test_workbench_active_is_saved_per_user(client, admin_token):
    r = client.get("/api/workbench/active", headers=auth(admin_token))
    assert r.status_code == 200
    original = r.json()["key"]
    try:
        r = client.put("/api/workbench/active", json={"key": "teacher"},
                       headers=auth(admin_token))
        assert r.status_code == 200 and r.json()["key"] == "teacher"
        r = client.get("/api/workbench/active", headers=auth(admin_token))
        assert r.json()["key"] == "teacher"
        r = client.put("/api/workbench/active", json={"key": ""},
                       headers=auth(admin_token))
        assert r.status_code == 200
        assert client.get("/api/workbench/active", headers=auth(admin_token)).json()["key"] == ""
    finally:
        client.put("/api/workbench/active", json={"key": original}, headers=auth(admin_token))


