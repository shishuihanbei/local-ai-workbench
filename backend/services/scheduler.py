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
from . import task_agent

log = logging.getLogger(__name__)

WEEK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
FREQUENCIES = {"once", "daily", "weekly", "monthly"}
TRIGGER_MODES = {"schedule", "event", "condition"}
NOTIFY_FORMATS = {"json", "text", "feishu", "dingtalk", "wecom"}
# 系统里当"触发器"的事件，加新事件只要在这里登记并调用 emit_event。
EVENT_LABELS = {
    "file.generated": "新生成文件",
    "ticket.created": "新服务台工单",
}
_running: set[int] = set()
_stop = asyncio.Event()
_worker: asyncio.Task | None = None
_slots: asyncio.Semaphore | None = None


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
    if str(task.get("trigger_mode") or "schedule") == "event":
        return "按事件触发"
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


def trigger_text(task: dict[str, Any]) -> str:
    mode = str(task.get("trigger_mode") or "schedule")
    if mode == "event":
        key = str(task.get("event_key") or "")
        label = EVENT_LABELS.get(key, key or "系统事件")
        flt = str(task.get("event_filter") or "").strip()
        return f"事件 · {label}" + (f"（含「{flt}」）" if flt else "")
    if mode == "condition":
        cond = str(task.get("condition") or "").strip()
        return "条件 · " + (cond[:40] + ("…" if len(cond) > 40 else "")) if cond else "条件触发"
    return ""


def event_matches(task: dict[str, Any], kind: str, text: str) -> bool:
    """事件任务是否该被这次事件触发：类型一致，且可选的关键词出现在事件文本里。"""
    if str(task.get("trigger_mode") or "") != "event":
        return False
    if str(task.get("event_key") or "") != kind:
        return False
    flt = str(task.get("event_filter") or "").strip().lower()
    if not flt:
        return True
    return flt in str(text or "").lower()


def parse_gate(text: str) -> bool:
    """条件判断的回答是否算"满足"。只认明确的否定，其余交给正常执行。"""
    body = str(text or "").strip()[:200]
    if not body:
        return False
    return "不满足" not in body and "未满足" not in body


def gate_message(task: dict[str, Any]) -> str:
    return (
        "【条件判断】你只负责判断下面这句话现在是否成立，不要开始执行任务本身。\n"
        f"条件：{str(task.get('condition') or '').strip()}\n"
        "只输出一行，严格用下面两种格式之一：\n"
        "满足：<写你判断成立的真实依据，30 字以内>\n"
        "不满足：<写你没看到什么或哪里不确定，30 字以内>\n"
        "必须换成真实理由，不要照抄格式里的说明文字；没有依据、拿不准就输出不满足。")


def _plain_summary(summary: str, limit: int = 400) -> str:
    return " ".join(str(summary or "").split())[:limit]


def notify_payload(fmt: str, title: str, text: str) -> dict[str, Any]:
    """把结果按目标渠道的消息格式包好；json 是通用格式，其余适配常见 IM。"""
    fmt = fmt if fmt in NOTIFY_FORMATS else "json"
    title = str(title or "任务结果")[:80]
    body = _plain_summary(text, 1200)
    if fmt == "feishu":
        return {"msg_type": "text", "content": {"text": f"{title}\n{body}"}}
    if fmt == "dingtalk":
        return {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}
    if fmt == "wecom":
        return {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}
    if fmt == "text":
        return {"title": title, "text": body}
    return {
        "title": title,
        "text": body,
        "status": "",
        "verdict": "",
        "conversation_id": None,
        "link": "",
    }


def valid_notify_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw or len(raw) > 500 or " " in raw:
        return False
    return raw.startswith("http://") or raw.startswith("https://")


def _parse_window(window: str) -> tuple[int, int]:
    raw = str(window or "00:00-07:00").strip()
    try:
        a, b = raw.split("-", 1)
        start = int(a.split(":")[0]) * 60 + int(a.split(":")[1])
        end = int(b.split(":")[0]) * 60 + int(b.split(":")[1])
    except Exception:
        start, end = 0, 7 * 60
    if not (0 <= start < 1440 and 0 <= end <= 1440) or start == end:
        start, end = 0, 7 * 60
    return start, end


def night_defer(now: float, window: str = "00:00-07:00",
                heavy: bool = True) -> float | None:
    """重任务在白天到点时改排进夜间窗口；已在窗口内返回 None 表示照常执行。

    夜间窗口支持跨零点（如 23:00-06:00）；跨零点时按"今天是否已在窗口"判断。
    """
    if not heavy:
        return None
    start, end = _parse_window(window)
    dt = datetime.fromtimestamp(now)
    minute = dt.hour * 60 + dt.minute
    inside = (start <= minute < end) if start < end else (minute >= start or minute < end)
    if inside:
        return None
    base = datetime.combine(dt.date(), dtime(0, 0)) + timedelta(minutes=start)
    if base.timestamp() <= now:
        base += timedelta(days=1)
    return base.timestamp()


def is_heavy(task: dict[str, Any]) -> bool:
    """带输出格式或提示词很长的任务视为重任务，白天不抢算力。"""
    if str(task.get("output_format") or "").strip():
        return True
    return len(str(task.get("prompt") or "")) >= 800


def public(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(task["id"]),
        "title": task.get("title") or "未命名任务",
        "prompt": task.get("prompt") or "",
        "frequency": task.get("frequency") or "once",
        "schedule": describe(task),
        "trigger_mode": task.get("trigger_mode") or "schedule",
        "trigger_text": trigger_text(task),
        "event_key": task.get("event_key") or "",
        "event_filter": task.get("event_filter") or "",
        "condition": task.get("condition") or "",
        "notify_channel": task.get("notify_channel") or "",
        "notify_url": task.get("notify_url") or "",
        "notify_format": task.get("notify_format") or "json",
        "notify_on": task.get("notify_on") or "ok",
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
        "last_verdict": task.get("last_verdict") or "",
        "memory": (task.get("memory") or "")[:1200],
        "goal": task.get("goal") or "",
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
        "verdict": row.get("verdict") or "",
        "attempts": int(row.get("attempts") or 0),
        "event": row.get("event") or "",
        "notified": bool(row.get("notified") or 0),
        "steps": task_agent.parse_steps(row.get("steps")),
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


async def _stream_chat(client: httpx.AsyncClient, access: str, payload: dict[str, Any],
                       task_id: int, run_id: int,
                       on_action=None) -> dict[str, Any]:
    """跑一轮对话，返回正文、文件、错误和工具轨迹。

    正文要累积下来：任务 Agent 的自检和任务档案都靠它判断这一轮到底
    有没有产出可用结论，只拿 done 里的 chars 是不够的。
    """
    content_parts: list[str] = []
    trace: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    error = ""
    summary = ""
    conversation_id: int | None = None
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
            elif etype == "delta":
                content_parts.append(str(event.get("text") or ""))
            elif etype == "agent_action":
                action = event.get("action") or {}
                trace.append(action)
                if on_action:
                    try:
                        await on_action(action)
                    except Exception:
                        log.debug("推送任务步骤失败", exc_info=True)
            elif etype == "error":
                error = str(event.get("message") or "生成失败")[:500]
            elif etype == "done":
                summary = str(event.get("summary") or "").strip()
                files = list(event.get("files") or [])
                if not summary:
                    count = int(event.get("chars") or 0)
                    summary = f"已生成回答（{count} 字）"
                if event.get("file_error"):
                    summary += "；" + str(event.get("file_error"))[:160]
                if files:
                    names = "、".join(str(f.get("name") or "") for f in files)
                    summary = f"已生成文件：{names}"
    return {
        "content": "".join(content_parts),
        "trace": trace,
        "files": files,
        "error": error,
        "summary": summary,
        "conversation_id": conversation_id,
        "task_id": task_id,
    }


async def emit_event(kind: str, *, user_id: int | None = None,
                     text: str = "") -> int:
    """系统事件入口：命中谁的事件任务就排队谁，不阻塞调用方。

    事件只在同一用户名下匹配（生成文件、工单都带 user_id），避免串号。
    """
    if kind not in EVENT_LABELS:
        return 0
    body = str(text or "")
    try:
        rows = await fetch_all(
            "SELECT * FROM scheduled_tasks WHERE enabled=1 AND trigger_mode='event' "
            "AND event_key=? ORDER BY id", (kind,))
        queued = 0
        for task in rows:
            if user_id and int(task["user_id"]) not in (int(user_id), 0):
                continue
            if not event_matches(task, kind, body):
                continue
            try:
                await queue_task(task, "event", event=f"{EVENT_LABELS.get(kind, kind)}：{body[:120]}")
                queued += 1
            except RuntimeError:
                continue
            except Exception:
                log.warning("事件任务排队失败 %s", task.get("id"), exc_info=True)
        return queued
    except Exception:
        log.warning("分发事件失败 %s", kind, exc_info=True)
        return 0


async def _daily_used(user_id: int) -> int:
    since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    row = await fetch_one(
        "SELECT COUNT(*) c FROM task_runs WHERE user_id=? AND started_at>=? "
        "AND trigger!='manual'", (user_id, since)) or {}
    return int(row.get("c") or 0)


async def _notify(task: dict[str, Any], *, status: str, verdict: str,
                  summary: str, conversation_id: int | None) -> tuple[bool, str]:
    """按任务配置投递结果；只发 http(s)，失败不重试、不影响任务本身。"""
    channel = str(task.get("notify_channel") or "").strip()
    if channel != "webhook":
        return False, ""
    url = str(task.get("notify_url") or "").strip()
    if not valid_notify_url(url):
        return False, "投递地址不是合法的 http/https 链接"
    fmt = str(task.get("notify_format") or "json")
    cfg = load_config()
    port = int(cfg.get("port") or 9000)
    title = f"【任务】{task.get('title') or '未命名任务'} · " + {
        "ok": "已完成", "skipped": "条件未满足", "error": "失败",
        "budget": "超出预算跳过", "stopped": "已停止"}.get(status, status)
    text = _plain_summary(summary, 1200)
    link = f"http://127.0.0.1:{port}/chat/{conversation_id}" if conversation_id else ""
    body = notify_payload(fmt, title, text)
    if fmt == "json":
        body.update({"status": status, "verdict": verdict,
                     "conversation_id": conversation_id, "link": link})
    elif link:
        if fmt == "text":
            body["link"] = link
        elif fmt == "feishu":
            body["content"]["text"] += f"\n{link}"
        elif fmt in ("dingtalk", "wecom"):
            body["text"]["content"] += f"\n{link}"
    try:
        timeout = httpx.Timeout(connect=6, read=10, write=10, pool=10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)
        if resp.status_code >= 300:
            return False, f"投递返回 {resp.status_code}"
        return True, ""
    except Exception as exc:
        return False, f"投递失败：{str(exc)[:120]}"


async def _auto_disable(task: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """连续失败达到阈值就自动暂停，避免每天无效空跑烧算力。"""
    limit = int(cfg.get("task_auto_disable_failures") or 0)
    if limit <= 0:
        return False
    rows = await fetch_all(
        "SELECT status FROM task_runs WHERE task_id=? AND status!='running' "
        "ORDER BY id DESC LIMIT ?", (int(task["id"]), limit))
    if len(rows) < limit or any(str(r.get("status")) != "error" for r in rows):
        return False
    note = f"连续 {limit} 次失败，已自动暂停任务；修好模型或提示词后手动启用。"
    now = time.time()
    await execute(
        "UPDATE scheduled_tasks SET enabled=0,next_run_at=NULL,last_result=?,updated_at=? "
        "WHERE id=?", (note, now, int(task["id"])))
    return True


async def _run_task(task: dict[str, Any], run_id: int, trigger: str) -> None:
    user_id = int(task["user_id"])
    sid = 0
    conversation_id: int | None = None
    summary = ""
    error = ""
    status = "ok"
    started = time.time()
    outcome: dict[str, Any] | None = None
    verdict = ""
    notified = False
    cfg = load_config()
    slot_held = False
    tid = int(task["id"])
    try:
        # 并发上限：满了就排队等槽位，不直接失败。
        if _slots is not None:
            await _slots.acquire()
            slot_held = True
        limit = int(cfg.get("task_daily_limit") or 0)
        if limit > 0 and trigger != "manual":
            used = await _daily_used(user_id)
            if used >= limit:
                status = "budget"
                error = f"今日自动运行已达上限 {limit} 次，这次跳过；可在配置里调高 task_daily_limit"
                summary = error
                raise _BudgetStop
        token, sid = await create_session(user_id, "127.0.0.1", "workbench-scheduler")
        access, _ = create_access_token(
            user_id, sid, f"task-{user_id}", "user", hours=2)
        model = str(task.get("model") or "").strip() or await _auto_model()
        if not model:
            raise RuntimeError("没有可用模型：请先启动本机模型，或在控制台「算力」页准备一个在线节点")
        base_payload = {
            "model": model,
            "agent_id": task.get("agent_id") or None,
            "output_format": task.get("output_format") or None,
            "web": bool(task.get("web_enabled")),
        }
        timeout = httpx.Timeout(connect=10, read=900, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def call(message: str, attempt: int) -> dict[str, Any]:
                payload = dict(base_payload, message=message)
                return await _stream_chat(client, access, payload, tid, run_id,
                                          on_action=push_action)

            async def push_action(action: dict[str, Any]) -> None:
                # 执行中就更新步骤，控制台不用等任务结束才看到进度。
                live.append({
                    "step": "tool",
                    "title": str(action.get("tool") or "") or "工具",
                    "status": str(action.get("status") or "ok"),
                    "detail": str(action.get("summary") or action.get("error") or "")[:180],
                    "dur_ms": int(action.get("dur_ms") or 0),
                })
                await _save_steps(run_id, live)

            live: list[dict[str, Any]] = task_agent.build_plan(task)
            await _save_steps(run_id, live)

            async def on_steps(steps: list[dict[str, Any]]) -> None:
                await _save_steps(run_id, steps)

            cond = str(task.get("condition") or "").strip()
            gate_step: dict[str, Any] | None = None
            passed = True
            if cond:
                # 条件判断先跑一轮轻量问答，成立才进入正式执行，省掉无效产出。
                gate = await _stream_chat(
                    client, access,
                    dict(base_payload, message=gate_message(task),
                         web=bool(task.get("web_enabled")), output_format=None),
                    tid, run_id, on_action=push_action)
                gate_text = str(gate.get("content") or "")
                if gate.get("conversation_id"):
                    conversation_id = int(gate["conversation_id"])
                    base_payload["conversation_id"] = conversation_id
                passed = parse_gate(gate_text)
                gate_step = {
                    "step": "gate",
                    "title": "条件判断",
                    "status": "ok" if passed else "skip",
                    "detail": _clip_gate(gate_text, 180),
                }
                live.insert(0, gate_step)
                await _save_steps(run_id, live)
                if not passed:
                    status = "skipped"
                    verdict = "skipped"
                    summary = "条件未满足，本轮跳过：" + (_clip_gate(gate_text, 120) or "没有明确成立")
                    error = ""

            if passed:
                outcome = await task_agent.run_task(
                    task, memory=str(task.get("memory") or ""), call=call,
                    on_steps=on_steps)
                if gate_step:
                    outcome["steps"].insert(0, gate_step)
                status = str(outcome.get("status") or "ok")
                verdict = str(outcome.get("verdict") or "")
                summary = str(outcome.get("summary") or "")
                error = str(outcome.get("error") or "")
                conversation_id = outcome.get("conversation_id") or conversation_id
    except _BudgetStop:
        verdict = "budget"
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
        if status in ("error", "budget") and error and not summary:
            # 失败时把真实原因带到任务列表，不要只显示“已生成回答（0 字）”。
            summary = error[:800]
        if sid:
            try:
                await revoke_session(sid)
            except Exception:
                pass
        try:
            memory = (str((outcome or {}).get("memory") or task.get("memory") or "")
                      if status == "ok" else str(task.get("memory") or ""))
            await execute(
                "UPDATE task_runs SET status=?,finished_at=?,conversation_id=?,summary=?,error=?,"
                "verdict=?,attempts=? WHERE id=?",
                (status, finished, conversation_id, summary[:800], error,
                 verdict or str((outcome or {}).get("verdict") or ""),
                 int((outcome or {}).get("attempts") or 0), run_id))
            await execute(
                "UPDATE scheduled_tasks SET last_run_at=?,last_status=?,last_result=?,"
                "last_conversation_id=?,memory=?,last_verdict=?,updated_at=? WHERE id=?",
                (finished, status, (summary or error)[:800], conversation_id,
                 memory, verdict, finished, tid))
            # 投递：默认为成功才发，勾了"每次都发"则失败、跳过也发。
            if str(task.get("notify_channel") or "") == "webhook":
                once = str(task.get("notify_on") or "ok")
                if once == "always" or status == "ok":
                    sent, why = await _notify(
                        task, status=status, verdict=verdict,
                        summary=summary or error, conversation_id=conversation_id)
                    notified = sent
                    if why:
                        await execute("UPDATE task_runs SET error=? WHERE id=?",
                                      (_join_reason(error, why), run_id))
            if notified:
                await execute("UPDATE task_runs SET notified=1 WHERE id=?", (run_id,))
            if status == "error" and await _auto_disable(task, cfg):
                await execute("UPDATE task_runs SET error=? WHERE id=?",
                              (_join_reason(error, "已自动暂停"), run_id))
        except Exception:
            log.exception("更新定时任务状态失败")
        _running.discard(tid)
        if slot_held and _slots is not None:
            _slots.release()


class _BudgetStop(Exception):
    """超出每日自动运行预算，不是故障，也不该重试。"""


def _clip_gate(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _join_reason(error: str, extra: str) -> str:
    return (str(error or "") + "；" + extra)[:800]


async def _save_steps(run_id: int, steps: list[dict[str, Any]]) -> None:
    """步骤轨迹落库；超长时只保留最近的部分，避免把运行表撑大。"""
    try:
        await execute("UPDATE task_runs SET steps=? WHERE id=?",
                      (json.dumps(steps, ensure_ascii=False)[:8000], run_id))
    except Exception:
        log.debug("保存任务步骤失败", exc_info=True)


async def queue_task(task: dict[str, Any], trigger: str = "schedule",
                     event: str = "") -> int:
    """创建一条运行记录并在后台执行；同一任务不会并行执行。"""
    tid = int(task["id"])
    if tid in _running:
        raise RuntimeError("这个任务正在执行")
    _running.add(tid)
    try:
        run_id = await execute(
            "INSERT INTO task_runs(task_id,user_id,trigger,status,started_at,event) "
            "VALUES(?,?,?,?,?,?)",
            (tid, int(task["user_id"]), trigger, "running", time.time(), str(event or "")[:200]))
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
            cfg = load_config()
            due = await fetch_all(
                "SELECT * FROM scheduled_tasks WHERE enabled=1 AND next_run_at IS NOT NULL "
                "AND next_run_at<=? ORDER BY next_run_at LIMIT 3", (now,))
            for task in due:
                tid = int(task["id"])
                if tid in _running:
                    continue
                if str(task.get("trigger_mode") or "schedule") == "event":
                    # 事件任务没有计划时间，靠 emit_event 触发，别在这里空转。
                    await execute(
                        "UPDATE scheduled_tasks SET next_run_at=NULL,updated_at=? WHERE id=?",
                        (now, tid))
                    continue
                if bool(cfg.get("task_heavy_night_only", True)):
                    defer = night_defer(
                        now, str(cfg.get("task_night_window") or "00:00-07:00"),
                        is_heavy(task))
                    if defer:
                        await execute(
                            "UPDATE scheduled_tasks SET next_run_at=?,updated_at=? WHERE id=?",
                            (defer, now, tid))
                        log.info("任务 %s 是重任务，改排到 %s", tid, fmt_time(defer))
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
    global _worker, _slots
    _stop.clear()
    if _worker and not _worker.done():
        return
    limit = max(1, int(load_config().get("task_max_concurrent") or 2))
    _slots = asyncio.Semaphore(limit)
    _worker = asyncio.create_task(_loop())
    log.info("定时任务调度器已启动（并发上限 %s）", limit)


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
