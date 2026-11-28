"""工作台：概览、定时任务、运行记录、自定义模板与分享。"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import execute, fetch_all, fetch_one
from ..security import current_user
from ..services import docgen, prompts, scheduler, skills

router = APIRouter(prefix="/api/workbench", tags=["workbench"])
PLUGIN_IDS = {"web", "kb", "docgen"}


@router.get("/catalog")
async def builtin_catalog(user: dict = Depends(current_user)):
    """内置工作台模板：后台可编辑，前端启动时拉取当前生效版本。"""
    return {"items": prompts.workbench_catalog(), "revision": prompts.revision()}


class QuickItem(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=600)
    format: str = ""


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="🧩", max_length=8)
    description: str = Field(default="", max_length=200)
    quick: list[QuickItem] = Field(min_length=1, max_length=8)
    skills: list[str] = Field(default_factory=list, max_length=12)
    skill_id: str = Field(default="", max_length=80)
    plugins: list[str] = Field(default_factory=list, max_length=8)


class ActiveBody(BaseModel):
    key: str = Field(default="", max_length=80)


class TemplateShareBody(TemplateBody):
    expires_days: int = Field(default=30, ge=0, le=365)


class TaskBody(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=3000)
    goal: str = Field(default="", max_length=600)
    frequency: str = "once"
    time_of_day: str = "09:00"
    weekdays: list[int] = Field(default_factory=lambda: [1])
    day_of_month: int = 1
    run_at: str | None = None
    model: str | None = None
    agent_id: int | None = None
    output_format: str | None = None
    web_enabled: bool = False
    enabled: bool = True
    trigger_mode: str = "schedule"
    event_key: str = ""
    event_filter: str = Field(default="", max_length=80)
    condition: str = Field(default="", max_length=600)
    notify_channel: str = ""
    notify_url: str = Field(default="", max_length=500)
    notify_format: str = "json"
    notify_on: str = "ok"


class ToggleBody(BaseModel):
    enabled: bool


def _parse_run_at(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt).timestamp()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _clean(body: TaskBody) -> dict[str, Any]:
    frequency = str(body.frequency or "once").strip().lower()
    if frequency not in scheduler.FREQUENCIES:
        raise HTTPException(400, "不支持的重复方式")
    mode = str(body.trigger_mode or "schedule").strip().lower()
    if mode not in scheduler.TRIGGER_MODES:
        raise HTTPException(400, "不支持的触发方式")
    event_key = str(body.event_key or "").strip()
    if mode == "event" and event_key not in scheduler.EVENT_LABELS:
        raise HTTPException(400, "不支持的事件类型")
    condition = str(body.condition or "").strip()
    if mode == "condition" and len(condition) < 4:
        raise HTTPException(400, "条件触发需要写清判断条件")
    channel = str(body.notify_channel or "").strip().lower()
    if channel not in ("", "webhook"):
        raise HTTPException(400, "不支持的结果投递渠道")
    notify_url = str(body.notify_url or "").strip()
    notify_format = str(body.notify_format or "json").strip().lower()
    if notify_format not in scheduler.NOTIFY_FORMATS:
        raise HTTPException(400, "不支持的投递格式")
    notify_on = str(body.notify_on or "ok").strip().lower()
    if notify_on not in ("ok", "always"):
        raise HTTPException(400, "投递时机只能是成功时或每次都发")
    if channel == "webhook" and not scheduler.valid_notify_url(notify_url):
        raise HTTPException(400, "投递地址需要是完整的 http/https 链接")
    weekdays = scheduler._parse_weekdays(body.weekdays)
    day = max(1, min(31, int(body.day_of_month or 1)))
    hh, mm = scheduler._parse_hhmm(body.time_of_day)
    run_at = _parse_run_at(body.run_at)
    if mode != "event" and frequency == "once":
        if not run_at:
            raise HTTPException(400, "一次性任务需要选择执行时间")
        if run_at <= time.time() + 60:
            raise HTTPException(400, "执行时间需要晚于当前时间至少 1 分钟")
    fmt = docgen.normalize_format(body.output_format)
    return {
        "title": body.title.strip(),
        "prompt": body.prompt.strip(),
        "goal": (body.goal or "").strip(),
        "trigger_mode": mode,
        "event_key": event_key if mode == "event" else "",
        "event_filter": str(body.event_filter or "").strip(),
        "condition": condition if mode == "condition" else "",
        "notify_channel": channel,
        "notify_url": notify_url if channel == "webhook" else "",
        "notify_format": notify_format,
        "notify_on": notify_on,
        "frequency": frequency,
        "run_at": run_at if frequency == "once" else None,
        "time_of_day": f"{hh:02d}:{mm:02d}",
        "weekdays": ",".join(str(x) for x in weekdays),
        "day_of_month": day,
        "model": (body.model or "").strip() or None,
        "agent_id": body.agent_id,
        "output_format": fmt,
        "web_enabled": 1 if body.web_enabled else 0,
        "enabled": 1 if body.enabled else 0,
    }


def _next_for(data: dict[str, Any]) -> float | None:
    if str(data.get("trigger_mode") or "schedule") == "event":
        # 事件任务没有计划时间，等事件发生才跑。
        return None
    return scheduler.next_run(data, after=time.time() + 2)


def _clean_template(body: TemplateBody) -> dict[str, Any]:
    quick: list[dict[str, str]] = []
    for item in body.quick:
        label = item.label.strip()
        text = item.text.strip()
        if not label and not text:
            continue
        if not label or not text:
            raise HTTPException(400, "每个快捷按钮都需要名称和提示词")
        quick.append({
            "label": label,
            "text": text,
            "format": docgen.normalize_format(item.format) or "",
        })
    if not quick:
        raise HTTPException(400, "至少保留一个快捷按钮")
    skills_list: list[str] = []
    for raw in ([body.skill_id] + list(body.skills or [])):
        sid = str(raw or "").strip()
        if sid and sid not in skills_list:
            skills_list.append(sid)
    for sid in skills_list:
        if not skills.get(sid):
            raise HTTPException(400, "选择的技能不存在或已停用")
    skill_id = skills_list[0] if skills_list else ""
    plugins = sorted({str(p).strip() for p in (body.plugins or []) if str(p).strip()})
    unknown = [p for p in plugins if p not in PLUGIN_IDS]
    if unknown:
        raise HTTPException(400, "包含不支持的插件：" + ", ".join(unknown))
    return {
        "name": body.name.strip(),
        "icon": (body.icon or "🧩").strip()[:8] or "🧩",
        "description": body.description.strip(),
        "quick_json": json.dumps(quick, ensure_ascii=False),
        "quick": quick,
        "skills": skills_list,
        "skill_id": skill_id,
        "skills_json": json.dumps(skills_list, ensure_ascii=False),
        "plugins_json": json.dumps(plugins, ensure_ascii=False),
        "plugins": plugins,
    }


def _public_template(row: dict[str, Any]) -> dict[str, Any]:
    try:
        quick = json.loads(row.get("quick_json") or "[]")
    except Exception:
        quick = []
    try:
        plugins = json.loads(row.get("plugins_json") or "[]")
    except Exception:
        plugins = []
    try:
        skills_list = json.loads(row.get("skills_json") or "[]")
    except Exception:
        skills_list = []
    if not isinstance(skills_list, list) or not skills_list:
        skills_list = [row.get("skill_id")] if row.get("skill_id") else []
    skills_list = [str(s) for s in skills_list if str(s)]
    skill_id = skills_list[0] if skills_list else ""
    skill = skills.get(skill_id) if skill_id else None
    skill_names = [((skills.get(sid) or {}).get("name") or sid) for sid in skills_list]
    return {
        "id": int(row.get("id") or 0),
        "name": row.get("name") or "",
        "icon": row.get("icon") or "🧩",
        "description": row.get("description") or "",
        "quick": quick if isinstance(quick, list) else [],
        "skills": skills_list,
        "skill_names": skill_names,
        "skill_id": skill_id,
        "skill_name": (skill or {}).get("name") or "",
        "plugins": plugins if isinstance(plugins, list) else [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.get("/active")
async def get_active(user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT template_key FROM workbench_active WHERE user_id=?", (int(user["id"]),))
    return {"key": (row or {}).get("template_key") or ""}


@router.put("/active")
async def set_active(body: ActiveBody, user: dict = Depends(current_user)):
    key = (body.key or "").strip()[:80]
    now = time.time()
    if key:
        await execute(
            "INSERT INTO workbench_active(user_id,template_key,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET template_key=excluded.template_key,"
            "updated_at=excluded.updated_at",
            (int(user["id"]), key, now))
    else:
        await execute(
            "INSERT INTO workbench_active(user_id,template_key,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET template_key='',updated_at=excluded.updated_at",
            (int(user["id"]), "", now))
    return {"ok": True, "key": key}


@router.get("/templates")
async def list_templates(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT * FROM workbench_templates WHERE user_id=? ORDER BY updated_at DESC, id DESC",
        (int(user["id"]),))
    return {"items": [_public_template(r) for r in rows]}


@router.post("/templates")
async def create_template(body: TemplateBody, user: dict = Depends(current_user)):
    data = _clean_template(body)
    now = time.time()
    tid = await execute(
        "INSERT INTO workbench_templates(user_id,name,icon,description,quick_json,skill_id,"
        "skills_json,plugins_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (int(user["id"]), data["name"], data["icon"], data["description"],
         data["quick_json"], data["skill_id"], data["skills_json"],
         data["plugins_json"], now, now))
    row = await fetch_one("SELECT * FROM workbench_templates WHERE id=?", (tid,))
    return _public_template(row or {})


@router.put("/templates/{template_id}")
async def update_template(template_id: int, body: TemplateBody, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT id FROM workbench_templates WHERE id=? AND user_id=?",
                          (template_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "工作台不存在")
    data = _clean_template(body)
    await execute(
        "UPDATE workbench_templates SET name=?,icon=?,description=?,quick_json=?,skill_id=?,"
        "skills_json=?,plugins_json=?,updated_at=? WHERE id=?",
        (data["name"], data["icon"], data["description"], data["quick_json"],
         data["skill_id"], data["skills_json"], data["plugins_json"],
         time.time(), template_id))
    updated = await fetch_one("SELECT * FROM workbench_templates WHERE id=?", (template_id,))
    return _public_template(updated or {})


@router.delete("/templates/{template_id}")
async def delete_template(template_id: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT id FROM workbench_templates WHERE id=? AND user_id=?",
                          (template_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "工作台不存在")
    await execute("DELETE FROM workbench_templates WHERE id=?", (template_id,))
    await execute(
        "UPDATE workbench_active SET template_key='',updated_at=? "
        "WHERE user_id=? AND template_key=?", (time.time(), int(user["id"]), f"custom-{template_id}"))
    return {"ok": True}


@router.post("/shares")
async def share_template(body: TemplateShareBody, user: dict = Depends(current_user)):
    data = _clean_template(body)
    now = time.time()
    token = secrets.token_urlsafe(12)
    expires_at = now + body.expires_days * 86400 if body.expires_days > 0 else None
    await execute(
        "INSERT INTO workbench_shares(owner_id,owner_name,title,icon,description,quick_json,"
        "skill_id,skills_json,plugins_json,token,expires_at,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(user["id"]), user.get("username", ""), data["name"], data["icon"],
         data["description"], data["quick_json"], data["skill_id"], data["skills_json"],
         data["plugins_json"], token, expires_at, now))
    return {"ok": True, "token": token, "url": f"/wb/{token}",
            "expires_at": expires_at}


@router.get("/shares/{token}")
async def read_template_share(token: str):
    row = await fetch_one(
        "SELECT * FROM workbench_shares WHERE token=? AND enabled=1", (token,))
    if not row:
        raise HTTPException(404, "这个工作台分享不存在或已撤销")
    expires_at = row.get("expires_at")
    if expires_at and float(expires_at) < time.time():
        raise HTTPException(404, "这个工作台分享已过期")
    await execute("UPDATE workbench_shares SET view_count=view_count+1 WHERE id=?", (row["id"],))
    data = _public_template({
        "id": row["id"], "name": row["title"], "icon": row["icon"],
        "description": row["description"], "quick_json": row["quick_json"],
        "skill_id": row.get("skill_id") or "",
        "skills_json": row.get("skills_json") or "[]",
        "plugins_json": row.get("plugins_json") or "[]",
        "created_at": row["created_at"], "updated_at": row["created_at"],
    })
    data.update({
        "owner_name": row.get("owner_name") or "成员",
        "view_count": int(row.get("view_count") or 0) + 1,
        "expires_at": expires_at,
    })
    return data


@router.get("/overview")
async def overview(user: dict = Depends(current_user)):
    uid = int(user["id"])
    conv_count = int((await fetch_one(
        "SELECT COUNT(*) c FROM conversations WHERE user_id=?", (uid,)) or {}).get("c") or 0)
    now = time.time()
    file_count = int((await fetch_one(
        "SELECT COUNT(*) c FROM generated_files WHERE user_id=? AND deleted_at=0 "
        "AND (expires_at=0 OR expires_at>?)", (uid, now)) or {}).get("c") or 0)
    task_count = int((await fetch_one(
        "SELECT COUNT(*) c FROM scheduled_tasks WHERE user_id=? AND enabled=1", (uid,)) or {}).get("c") or 0)
    since = time.time() - 86400
    run_count = int((await fetch_one(
        "SELECT COUNT(*) c FROM task_runs WHERE user_id=? AND started_at>=?", (uid, since)) or {}).get("c") or 0)
    tasks = await fetch_all(
        "SELECT * FROM scheduled_tasks WHERE user_id=? AND enabled=1 "
        "AND next_run_at IS NOT NULL ORDER BY next_run_at LIMIT 5", (uid,))
    files = await fetch_all(
        "SELECT id,name,kind,size,created_at,expires_at,deleted_at,conversation_id "
        "FROM generated_files WHERE user_id=? AND deleted_at=0 "
        "AND (expires_at=0 OR expires_at>?) ORDER BY id DESC LIMIT 6", (uid, now))
    files = [docgen.decorate_row(dict(r), now) for r in (files or [])]
    conversations = await fetch_all(
        "SELECT id,title,updated_at FROM conversations WHERE user_id=? "
        "ORDER BY updated_at DESC LIMIT 6", (uid,))
    runs = await fetch_all(
        "SELECT * FROM task_runs WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
    return {
        "counts": {"conversations": conv_count, "files": file_count,
                   "tasks": task_count, "runs_24h": run_count},
        "upcoming": [scheduler.public(t) for t in tasks],
        "files": files,
        "conversations": conversations,
        "runs": [scheduler.public_run(r) for r in runs],
    }


@router.get("/tasks")
async def list_tasks(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT * FROM scheduled_tasks WHERE user_id=? "
        "ORDER BY enabled DESC, next_run_at ASC, id DESC", (int(user["id"]),))
    items = []
    for r in rows:
        item = scheduler.public(r)
        # 附带最近一次运行的步骤轨迹，前端不用再单独拉一次运行记录。
        last = await fetch_one(
            "SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (int(r["id"]),))
        item["last_run"] = scheduler.public_run(last) if last else None
        items.append(item)
    return {"items": items}


@router.post("/tasks")
async def create_task(body: TaskBody, user: dict = Depends(current_user)):
    data = _clean(body)
    nxt = _next_for(data)
    if data["enabled"] and data["trigger_mode"] != "event" and not nxt:
        raise HTTPException(400, "这个时间已经过去，请重新选择")
    now = time.time()
    tid = await execute(
        "INSERT INTO scheduled_tasks(user_id,title,prompt,goal,trigger_mode,event_key,event_filter,"
        "condition,notify_channel,notify_url,notify_format,notify_on,frequency,run_at,time_of_day,"
        "weekdays,day_of_month,model,agent_id,output_format,web_enabled,enabled,next_run_at,"
        "created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(user["id"]), data["title"], data["prompt"], data["goal"], data["trigger_mode"],
         data["event_key"], data["event_filter"], data["condition"], data["notify_channel"],
         data["notify_url"], data["notify_format"], data["notify_on"], data["frequency"],
         data["run_at"], data["time_of_day"], data["weekdays"], data["day_of_month"],
         data["model"], data["agent_id"], data["output_format"], data["web_enabled"],
         data["enabled"], nxt if data["enabled"] else None, now, now))
    row = await fetch_one("SELECT * FROM scheduled_tasks WHERE id=?", (tid,))
    return scheduler.public(row or {})


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, body: TaskBody, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT * FROM scheduled_tasks WHERE id=? AND user_id=?",
                          (task_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "任务不存在")
    data = _clean(body)
    nxt = _next_for(data)
    if data["enabled"] and data["trigger_mode"] != "event" and not nxt:
        raise HTTPException(400, "这个时间已经过去，请重新选择")
    now = time.time()
    # 目标被改写后旧档案就是干扰项，直接清空，让任务从新目标重新积累。
    reset_memory = 1 if str(row.get("prompt") or "").strip() != data["prompt"] else 0
    await execute(
        "UPDATE scheduled_tasks SET title=?,prompt=?,goal=?,trigger_mode=?,event_key=?,"
        "event_filter=?,condition=?,notify_channel=?,notify_url=?,notify_format=?,notify_on=?,"
        "frequency=?,run_at=?,time_of_day=?,weekdays=?,day_of_month=?,model=?,agent_id=?,"
        "output_format=?,web_enabled=?,enabled=?,next_run_at=?,"
        "memory=CASE WHEN ?=1 THEN '' ELSE memory END,updated_at=? WHERE id=?",
        (data["title"], data["prompt"], data["goal"], data["trigger_mode"], data["event_key"],
         data["event_filter"], data["condition"], data["notify_channel"], data["notify_url"],
         data["notify_format"], data["notify_on"], data["frequency"], data["run_at"],
         data["time_of_day"], data["weekdays"], data["day_of_month"], data["model"],
         data["agent_id"], data["output_format"], data["web_enabled"], data["enabled"],
         nxt if data["enabled"] else None, reset_memory, now, task_id))
    updated = await fetch_one("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,))
    return scheduler.public(updated or {})


@router.patch("/tasks/{task_id}")
async def toggle_task(task_id: int, body: ToggleBody, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT * FROM scheduled_tasks WHERE id=? AND user_id=?",
                          (task_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "任务不存在")
    enabled = 1 if body.enabled else 0
    mode = str(row.get("trigger_mode") or "schedule")
    nxt = _next_for({**row, "trigger_mode": mode}) if enabled else None
    if enabled and mode != "event" and not nxt:
        raise HTTPException(400, "任务时间已过，请先编辑时间")
    await execute(
        "UPDATE scheduled_tasks SET enabled=?,next_run_at=?,updated_at=? WHERE id=?",
        (enabled, nxt, time.time(), task_id))
    updated = await fetch_one("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,))
    return scheduler.public(updated or {})


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT id FROM scheduled_tasks WHERE id=? AND user_id=?",
                          (task_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "任务不存在")
    await execute("DELETE FROM task_runs WHERE task_id=?", (task_id,))
    await execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
    return {"ok": True}


@router.get("/events")
async def event_catalog(user: dict = Depends(current_user)):
    """可用的事件触发类型，前端下拉直接用。"""
    return {"items": [{"key": k, "label": v} for k, v in scheduler.EVENT_LABELS.items()]}


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT * FROM scheduled_tasks WHERE id=? AND user_id=?",
                          (task_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "任务不存在")
    try:
        run_id = await scheduler.queue_task(row, "manual")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "run_id": run_id}


@router.get("/tasks/{task_id}/runs")
async def task_runs(task_id: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT id FROM scheduled_tasks WHERE id=? AND user_id=?",
                          (task_id, int(user["id"])))
    if not row:
        raise HTTPException(404, "任务不存在")
    rows = await fetch_all(
        "SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 30", (task_id,))
    return {"items": [scheduler.public_run(r) for r in rows]}


@router.get("/runs")
async def recent_runs(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT * FROM task_runs WHERE user_id=? ORDER BY id DESC LIMIT 30",
        (int(user["id"]),))
    return {"items": [scheduler.public_run(r) for r in rows]}
