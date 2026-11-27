"""定时任务：计划计算、到点执行、运行记录。

任务执行通过本机 API 复用正常聊天链路：会创建独立会话、写入用户消息、调用模型，
如果任务选择了输出格式，还会生成可下载文件。这样“定时任务”看到的就是和手动聊天
完全一致的结果，而不是另造一套简化回答。
"""
from __future__ import annotations

import asyncio
import calendar
import json
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

import httpx

from ..config import load_config
from ..db import execute, fetch_all, fetch_one
from ..security import create_access_token, create_session, revoke_session

log = logging.getLogger(__name__)

WEEK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
FREQUENCIES = {"once", "daily", "weekly", "monthly"}
_running: set[int] = set()
_stop = asyncio.Event()
_worker: asyncio.Task | None = None


def _parse_hhmm(value: str, fallback: str = "09:00") -> tuple[int, int]:
    raw = str(value or fallback).strip()
    try:
        hh, mm = raw.split(":", 1)
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except Exception:
        pass
    hh, mm = fallback.split(":", 1)
    return int(hh), int(mm)


def _parse_weekdays(value: str | list[int] | None) -> list[int]:
    if isinstance(value, list):
        raw = value
    else:
        raw = [x for x in str(value or "").replace("，", ",").split(",") if str(x).strip()]
    out: list[int] = []
    for x in raw:
        try:
            n = int(x)
        except Exception:
            continue
        if 1 <= n <= 7 and n not in out:
            out.append(n)
    return out or [1]


def _clamped_date(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, day), last))


def next_run(task: dict[str, Any], after: float | None = None) -> float | None:
    """返回下一次运行时间；一次性任务已经过期则返回 None。"""
    base = float(after if after is not None else time.time())
    freq = str(task.get("frequency") or "once")
    if freq == "once":
        run_at = task.get("run_at")
        try:
            ts = float(run_at) if run_at is not None else 0
        except Exception:
            ts = 0
        return ts if ts > base + 1 else None

    now = datetime.fromtimestamp(base)
    h, m = _parse_hhmm(str(task.get("time_of_day") or "09:00"))
    if freq == "daily":
        cand = datetime.combine(now.date(), dtime(h, m))
        if cand.timestamp() <= base + 1:
            cand += timedelta(days=1)
        return cand.timestamp()

    if freq == "weekly":
        wanted = set(_parse_weekdays(task.get("weekdays")))
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            if day.isoweekday() not in wanted:
                continue
            cand = datetime.combine(day, dtime(h, m))
            if cand.timestamp() > base + 1:
                return cand.timestamp()
        return None

    if freq == "monthly":
        day_num = int(task.get("day_of_month") or 1)
        year, month = now.year, now.month
        for _ in range(14):
            target = _clamped_date(year, month, day_num)
            cand = datetime.combine(target, dtime(h, m))
            if cand.timestamp() > base + 1:
                return cand.timestamp()
            month += 1
            if month > 12:
                month = 1
                year += 1
        return None
    return None


def describe(task: dict[str, Any]) -> str:
    freq = str(task.get("frequency") or "once")
    hhmm = str(task.get("time_of_day") or "09:00")
    if freq == "daily":
        return f"每天 {hhmm}"
    if freq == "weekly":
        labels = "、".join(WEEK_LABELS[n - 1] for n in _parse_weekdays(task.get("weekdays")))
        return f"每{labels} {hhmm}"
    if freq == "monthly":
        return f"每月 {int(task.get('day_of_month') or 1)} 日 {hhmm}"
    try:
        dt = datetime.fromtimestamp(float(task.get("run_at") or 0))
        return f"一次性 · {dt.strftime('%Y-%m-%d %H:%M')}"
    except Exception:
        return "一次性"


def fmt_time(ts: Any) -> str:
    try:
        n = float(ts or 0)
        if n <= 0:
            return ""
        return datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def public(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(task["id"]),
        "title": task.get("title") or "未命名任务",
        "prompt": task.get("prompt") or "",
        "frequency": task.get("frequency") or "once",
        "schedule": describe(task),
        "time_of_day": task.get("time_of_day") or "09:00",
        "weekdays": _parse_weekdays(task.get("weekdays")),
        "day_of_month": int(task.get("day_of_month") or 1),
        "run_at": task.get("run_at"),
        "run_at_text": fmt_time(task.get("run_at")),
        "model": task.get("model") or "",
        "agent_id": task.get("agent_id"),
        "output_format": task.get("output_format") or "",
        "web_enabled": bool(task.get("web_enabled")),
        "enabled": bool(task.get("enabled")),
        "next_run_at": task.get("next_run_at"),
        "next_run_text": fmt_time(task.get("next_run_at")),
        "last_run_at": task.get("last_run_at"),
        "last_run_text": fmt_time(task.get("last_run_at")),
        "last_status": task.get("last_status") or "",
        "last_result": task.get("last_result") or "",
        "last_conversation_id": task.get("last_conversation_id"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


def public_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "task_id": int(row["task_id"]),
        "trigger": row.get("trigger") or "schedule",
        "status": row.get("status") or "",
        "started_at": row.get("started_at"),
        "started_text": fmt_time(row.get("started_at")),
        "finished_at": row.get("finished_at"),
        "finished_text": fmt_time(row.get("finished_at")),
        "conversation_id": row.get("conversation_id"),
        "summary": row.get("summary") or "",
        "error": row.get("error") or "",
    }


def _local_api_base() -> str:
    cfg = load_config()
    port = int(cfg.get("port") or 9000)
    return f"http://127.0.0.1:{port}"


async def _auto_model() -> str:
    """给「自动选择」挑一个此刻真能跑的模型。

    定时任务没有浏览器里那份模型下拉，必须先按可用性挑：算力池节点在线、
    本地 llama.cpp 正在服务、或已有可达平台模型，避免把任务打到没启动的本地端口。
    """
    from . import cluster, llama, platform_models

    pools = await fetch_all(
        "SELECT DISTINCT p.name FROM cluster_pools p "
        "JOIN cluster_members m ON m.pool_id=p.id AND m.enabled=1 "
        "JOIN cluster_nodes n ON n.id=m.node_id AND n.enabled=1 "
        "WHERE p.enabled=1 ORDER BY p.id")
    for row in pools:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        _, nodes = await cluster.candidates(name)
        if any(node.get("status") != "offline" for node in nodes):
            return name

    cfg = load_config()
    try:
        status = await llama.status()
    except Exception:
        status = {}
    if status.get("running"):
        return str(status.get("model") or cfg.get("model") or "").strip()

    try:
        for item in await platform_models.reachable(cfg):
            key = str(item.get("key") or "").strip()
            if key:
                return key
    except Exception:
        pass
    return ""


async def _run_task(task: dict[str, Any], run_id: int, trigger: str) -> None:
    user_id = int(task["user_id"])
    sid = 0
    conversation_id: int | None = None
    summary = ""
    error = ""
    status = "ok"
    started = time.time()
    try:
        token, sid = await create_session(user_id, "127.0.0.1", "workbench-scheduler")
        access, _ = create_access_token(
            user_id, sid, f"task-{user_id}", "user", hours=2)
        model = str(task.get("model") or "").strip() or await _auto_model()
        if not model:
            raise RuntimeError("没有可用模型：请先启动本机模型，或在控制台「算力」页准备一个在线节点")
        payload = {
            "message": task.get("prompt") or "",
            "model": model,
            "agent_id": task.get("agent_id") or None,
            "output_format": task.get("output_format") or None,
            "web": bool(task.get("web_enabled")),
        }
        timeout = httpx.Timeout(connect=10, read=900, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                    "POST", _local_api_base() + "/api/chat/stream", json=payload,
                    headers={"Authorization": f"Bearer {access}"}) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise RuntimeError(f"任务接口返回 {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue
                    etype = event.get("type")
                    if etype == "meta":
                        conversation_id = int(event.get("conversation_id") or 0) or None
                        if conversation_id:
                            await execute(
                                "UPDATE task_runs SET conversation_id=? WHERE id=?",
                                (conversation_id, run_id))
                    elif etype == "error":
                        error = str(event.get("message") or "生成失败")[:500]
                        status = "error"
                    elif etype == "done":
                        summary = str(event.get("summary") or "").strip()
                        if not summary:
                            count = int(event.get("chars") or 0)
                            summary = f"已生成回答（{count} 字）"
                        if event.get("file_error"):
                            summary += "；" + str(event.get("file_error"))[:160]
                        files = event.get("files") or []
                        if files:
                            names = "、".join(str(f.get("name") or "") for f in files)
                            summary = f"已生成文件：{names}"
    except asyncio.CancelledError:
        status = "stopped"
        error = "服务停止"
        raise
    except Exception as exc:
        status = "error"
        error = str(exc)[:500]
        log.warning("定时任务 %s 执行失败: %s", task.get("id"), error)
    finally:
        finished = time.time()
        if status != "ok" and error:
            # 失败时把真实原因带到任务列表，不要只显示“已生成回答（0 字）”。
            summary = error[:800]
        if sid:
            try:
                await revoke_session(sid)
            except Exception:
                pass
        try:
            await execute(
                "UPDATE task_runs SET status=?,finished_at=?,conversation_id=?,summary=?,error=? "
                "WHERE id=?",
                (status, finished, conversation_id, summary[:800], error, run_id))
            await execute(
                "UPDATE scheduled_tasks SET last_run_at=?,last_status=?,last_result=?,"
                "last_conversation_id=?,updated_at=? WHERE id=?",
                (finished, status, (summary or error)[:800], conversation_id,
                 finished, int(task["id"])))
        except Exception:
            log.exception("更新定时任务状态失败")
        _running.discard(int(task["id"]))


async def queue_task(task: dict[str, Any], trigger: str = "schedule") -> int:
    """创建一条运行记录并在后台执行；同一任务不会并行执行。"""
    tid = int(task["id"])
    if tid in _running:
        raise RuntimeError("这个任务正在执行")
    _running.add(tid)
    try:
        run_id = await execute(
            "INSERT INTO task_runs(task_id,user_id,trigger,status,started_at) "
            "VALUES(?,?,?,?,?)",
            (tid, int(task["user_id"]), trigger, "running", time.time()))
        await execute(
            "UPDATE scheduled_tasks SET last_status='running',updated_at=? WHERE id=?",
            (time.time(), tid))
    except Exception:
        _running.discard(tid)
        raise
    asyncio.create_task(_run_task(task, int(run_id), trigger))
    return int(run_id)


async def _loop() -> None:
    await asyncio.sleep(10)
    while not _stop.is_set():
        try:
            now = time.time()
            due = await fetch_all(
                "SELECT * FROM scheduled_tasks WHERE enabled=1 AND next_run_at IS NOT NULL "
                "AND next_run_at<=? ORDER BY next_run_at LIMIT 3", (now,))
            for task in due:
                tid = int(task["id"])
                if tid in _running:
                    continue
                try:
                    await queue_task(task, "schedule")
                except Exception as e:
                    log.warning("排队定时任务失败 %s: %s", tid, e)
                    continue
                if str(task.get("frequency")) == "once":
                    await execute(
                        "UPDATE scheduled_tasks SET enabled=0,next_run_at=NULL,updated_at=? "
                        "WHERE id=?", (now, tid))
                else:
                    follow = next_run(task, after=now + 2)
                    await execute(
                        "UPDATE scheduled_tasks SET next_run_at=?,updated_at=? WHERE id=?",
                        (follow, now, tid))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("定时任务检查失败")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=25)
        except asyncio.TimeoutError:
            pass


async def start() -> None:
    global _worker
    _stop.clear()
    if _worker and not _worker.done():
        return
    _worker = asyncio.create_task(_loop())
    log.info("定时任务调度器已启动")


async def stop() -> None:
    global _worker
    _stop.set()
    if _worker and not _worker.done():
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
    _worker = None
