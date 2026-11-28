"""任务 Agent P2：事件触发、条件判断、结果投递与预算治理。"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

from conftest import auth


def test_event_matching_and_labels():
    from backend.services import scheduler

    task = {"trigger_mode": "event", "event_key": "file.generated", "event_filter": "周报"}
    assert scheduler.event_matches(task, "file.generated", "本周周报.docx Word 文档")
    assert not scheduler.event_matches(task, "file.generated", "数据表.xlsx")
    assert not scheduler.event_matches(task, "ticket.created", "本周周报")
    plain = {"trigger_mode": "event", "event_key": "ticket.created", "event_filter": ""}
    assert scheduler.event_matches(plain, "ticket.created", "无法登录")
    schedule = {"trigger_mode": "schedule", "event_key": "ticket.created"}
    assert not scheduler.event_matches(schedule, "ticket.created", "任意内容")
    assert scheduler.EVENT_LABELS["file.generated"] == "新生成文件"


def test_gate_and_trigger_text():
    from backend.services import scheduler

    assert scheduler.parse_gate("满足：今天确实出现了降价消息")
    assert not scheduler.parse_gate("不满足：今天没有相关动态")
    assert not scheduler.parse_gate("")
    event_task = {"trigger_mode": "event", "event_key": "file.generated",
                  "event_filter": "周报"}
    assert "新生成文件" in scheduler.trigger_text(event_task)
    assert "周报" in scheduler.trigger_text(event_task)
    cond_task = {"trigger_mode": "condition", "condition": "出现降价才产出结果"}
    assert scheduler.trigger_text(cond_task).startswith("条件 · 出现降价")
    gate = scheduler.gate_message({"condition": "今天是否出现降价"})
    assert "不要照抄" in gate and "满足：" in gate and "不满足：" in gate


def test_notify_payload_formats():
    from backend.services import scheduler

    base = scheduler.notify_payload("json", "标题", "正文内容")
    assert base["title"] == "标题" and base["text"] == "正文内容"
    assert scheduler.notify_payload("feishu", "标题", "正文内容")["msg_type"] == "text"
    assert scheduler.notify_payload("dingtalk", "标题", "正文内容")["msgtype"] == "text"
    assert scheduler.notify_payload("wecom", "标题", "正文内容")["msgtype"] == "text"
    assert scheduler.notify_payload("text", "标题", "正文内容") == {
        "title": "标题", "text": "正文内容"}
    assert not scheduler.valid_notify_url("ftp://x/y")
    assert not scheduler.valid_notify_url("javascript:alert(1)")
    assert scheduler.valid_notify_url("https://example.com/hook")


def test_night_defer_windows():
    from backend.services import scheduler

    noon = datetime(2026, 11, 28, 14, 0).timestamp()
    defer = scheduler.night_defer(noon, "00:00-07:00", True)
    assert datetime.fromtimestamp(defer).strftime("%Y-%m-%d %H:%M") == "2026-11-29 00:00"
    inside = datetime(2026, 11, 28, 3, 0).timestamp()
    assert scheduler.night_defer(inside, "00:00-07:00", True) is None
    assert scheduler.night_defer(noon, "00:00-07:00", False) is None
    cross = datetime(2026, 11, 28, 23, 30).timestamp()
    assert scheduler.night_defer(cross, "23:00-06:00", True) is None
    assert scheduler.night_defer(noon, "23:00-06:00", True) is not None


def test_is_heavy():
    from backend.services import scheduler

    assert scheduler.is_heavy({"output_format": "docx"})
    assert scheduler.is_heavy({"prompt": "很长的要求" * 200})
    assert not scheduler.is_heavy({"output_format": "", "prompt": "整理今天的动态"})


def test_event_task_create_and_validation(client, admin_token):
    r = client.get("/api/workbench/events", headers=auth(admin_token))
    assert r.status_code == 200
    keys = {x["key"] for x in r.json()["items"]}
    assert {"file.generated", "ticket.created"} <= keys

    base = {
        "title": "生成文件后自动写摘要",
        "prompt": "文件生成后写一段 100 字以内的摘要。",
        "trigger_mode": "event",
        "event_key": "file.generated",
        "event_filter": "周报",
        "frequency": "daily",
        "time_of_day": "09:00",
        "enabled": True,
    }
    r = client.post("/api/workbench/tasks", json=base, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["trigger_mode"] == "event"
    assert task["next_run_at"] in (None, "")
    assert "事件" in task["trigger_text"]
    client.delete(f"/api/workbench/tasks/{task['id']}", headers=auth(admin_token))

    r = client.post("/api/workbench/tasks", json={**base, "event_key": "未知事件"},
                    headers=auth(admin_token))
    assert r.status_code == 400

    r = client.post("/api/workbench/tasks", json={**base, "trigger_mode": "condition",
                                                  "condition": "x"}, headers=auth(admin_token))
    assert r.status_code == 400

    r = client.post("/api/workbench/tasks", json={
        "title": "条件任务", "prompt": "有降价就写简报", "trigger_mode": "condition",
        "condition": "今天的动态中是否出现降价", "frequency": "daily",
        "time_of_day": "09:00", "enabled": True}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    cond = r.json()
    assert cond["condition"].startswith("今天的动态")
    client.delete(f"/api/workbench/tasks/{cond['id']}", headers=auth(admin_token))

    r = client.post("/api/workbench/tasks", json={
        "title": "非法投递", "prompt": "测试", "trigger_mode": "schedule",
        "frequency": "daily", "time_of_day": "09:00", "enabled": True,
        "notify_channel": "webhook", "notify_url": "ftp://bad/hook",
    }, headers=auth(admin_token))
    assert r.status_code == 400

    r = client.post("/api/workbench/tasks", json={
        "title": "正常投递", "prompt": "测试", "trigger_mode": "schedule",
        "frequency": "daily", "time_of_day": "09:00", "enabled": True,
        "notify_channel": "webhook", "notify_url": "https://example.com/hook",
        "notify_format": "feishu", "notify_on": "always"}, headers=auth(admin_token))
    assert r.status_code == 200, r.text
    webhook = r.json()
    assert webhook["notify_channel"] == "webhook"
    assert webhook["notify_format"] == "feishu"
    client.delete(f"/api/workbench/tasks/{webhook['id']}", headers=auth(admin_token))


def test_emit_event_matches_only_same_kind_and_user(client, admin_token, monkeypatch):
    from backend.db import execute, fetch_one
    from backend.services import scheduler

    uid = 1
    nxt = (datetime.now() + timedelta(hours=4)).timestamp()
    tid = asyncio.run(execute(
        "INSERT INTO scheduled_tasks(user_id,title,prompt,trigger_mode,event_key,"
        "event_filter,frequency,enabled,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uid, "事件冒烟", "写摘要", "event", "file.generated", "周报",
         "daily", 1, time.time(), time.time())))
    other = asyncio.run(execute(
        "INSERT INTO scheduled_tasks(user_id,title,prompt,trigger_mode,event_key,"
        "frequency,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (uid, "不相关事件", "写摘要", "event", "ticket.created",
         "daily", 1, time.time(), time.time())))  # noqa: F841
    queued: list[tuple[int, str]] = []

    async def fake_queue(task, trigger="schedule", event=""):
        queued.append((int(task["id"]), trigger))
        return 1

    monkeypatch.setattr(scheduler, "queue_task", fake_queue)
    try:
        n = asyncio.run(scheduler.emit_event(
            "file.generated", user_id=uid, text="年度周报.docx Word 文档"))
        assert n == 1
        assert queued and queued[0] == (tid, "event")
        n2 = asyncio.run(scheduler.emit_event(
            "file.generated", user_id=uid, text="普通数据.xlsx"))
        assert n2 == 0
        n3 = asyncio.run(scheduler.emit_event(
            "file.generated", user_id=999, text="年度周报.docx"))
        assert n3 == 0
        row = asyncio.run(fetch_one("SELECT id FROM scheduled_tasks WHERE id=?", (tid,)))
        assert row is not None
    finally:
        asyncio.run(execute("DELETE FROM scheduled_tasks WHERE title IN ('事件冒烟','不相关事件')"))


def test_budget_stops_automatic_run(client, admin_token, monkeypatch):
    from backend.db import execute, fetch_one
    from backend.services import scheduler

    cfg = {"task_daily_limit": 1, "task_max_concurrent": 2,
           "task_auto_disable_failures": 0, "task_heavy_night_only": False}
    monkeypatch.setattr(scheduler, "load_config", lambda: cfg)
    now = time.time()
    uid = 1
    tid = asyncio.run(execute(
        "INSERT INTO scheduled_tasks(user_id,title,prompt,frequency,enabled,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (uid, "预算任务", "写一句话", "daily", 1, now, now)))
    marker = asyncio.run(execute(
        "INSERT INTO task_runs(task_id,user_id,trigger,status,started_at) "
        "VALUES(?,?,?,?,?)", (0, uid, "schedule", "ok", now)))
    run_id = asyncio.run(execute(
        "INSERT INTO task_runs(task_id,user_id,trigger,status,started_at) "
        "VALUES(?,?,?,?,?)", (tid, uid, "schedule", "running", now)))
    try:
        task = asyncio.run(fetch_one("SELECT * FROM scheduled_tasks WHERE id=?", (tid,)))
        asyncio.run(scheduler._run_task(dict(task), int(run_id), "schedule"))
        run = asyncio.run(fetch_one("SELECT * FROM task_runs WHERE id=?", (run_id,)))
        assert run["status"] == "budget"
        assert "上限" in (run["summary"] or "")
        assert run["verdict"] == "budget"
    finally:
        asyncio.run(execute("DELETE FROM task_runs WHERE task_id=? OR id IN (?,?)",
                            (tid, run_id, marker)))
        asyncio.run(execute("DELETE FROM scheduled_tasks WHERE id=?", (tid,)))


def test_daily_budget_counts_only_automatic_runs(client, admin_token):
    from backend.db import execute, fetch_one
    from backend.services import scheduler

    before = asyncio.run(scheduler._daily_used(1))
    rid = asyncio.run(execute(
        "INSERT INTO task_runs(task_id,user_id,trigger,status,started_at) "
        "VALUES(?,?,?,?,?)", (0, 1, "schedule", "ok", time.time())))
    try:
        after = asyncio.run(scheduler._daily_used(1))
        assert after == before + 1
    finally:
        asyncio.run(execute("DELETE FROM task_runs WHERE id=?", (rid,)))
    assert asyncio.run(fetch_one(
        "SELECT COUNT(*) c FROM task_runs WHERE trigger='manual' AND user_id=1")) is not None
