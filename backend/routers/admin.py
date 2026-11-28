"""管理面 API：概览、调用记录、供应商、路由。"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..db import audit, execute, fetch_all, fetch_one
from ..config import load_config, save_config
from ..security import admin_user
from ..services import assist, branding, moderation, secrets_store, skills

router = APIRouter(prefix="/api/admin", tags=["admin"])


class OrgBody(BaseModel):
    org_name: str = Field(min_length=1, max_length=60)
    org_short_name: str = Field(default="", max_length=30)
    org_domain: str = Field(default="", max_length=120)
    org_industry: str = Field(default="", max_length=40)
    org_size: str = Field(default="", max_length=40)
    org_contact_name: str = Field(default="", max_length=40)
    org_contact_email: str = Field(default="", max_length=120)
    brand_tagline: str = Field(default="", max_length=60)
    brand_login_title: str = Field(default="", max_length=120)
    brand_login_lead: str = Field(default="", max_length=320)
    brand_login_foot: str = Field(default="", max_length=120)
    brand_auth_subtitle: str = Field(default="", max_length=120)
    brand_primary: str = Field(default="", max_length=20)
    brand_icp: str = Field(default="", max_length=80)
    brand_icp_url: str = Field(default="", max_length=500)
    brand_police: str = Field(default="", max_length=100)
    brand_police_url: str = Field(default="", max_length=500)
    brand_copyright: str = Field(default="", max_length=120)
    watermark_enabled: bool = False
    watermark_text: str = Field(default="{user} · {org} · 内部资料", max_length=100)


def _mask(key: str) -> str:
    if not key:
        return ""
    return "****" + key[-4:] if len(key) > 4 else "****"


def _num(v, default=0.0):
    try:
        return float(v or default)
    except Exception:
        return default


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round((p / 100) * (len(values) - 1)))))
    return round(values[k], 1)


# ------------------------------------------------------------------ 概览
@router.get("/overview")
async def overview(days: int = Query(1, ge=1, le=30), user: dict = Depends(admin_user)):
    since = time.time() - days * 86400
    total = await fetch_one(
        "SELECT COUNT(*) c, SUM(total_tokens) tk, SUM(cost) cost, "
        "SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) err, "
        "SUM(CASE WHEN provider='local' THEN 1 ELSE 0 END) local_c, "
        "SUM(cache_hit) cache_c FROM requests WHERE created_at>=?", (since,)) or {}
    count = total.get("c") or 0
    rows = await fetch_all(
        "SELECT ttft_ms,total_ms FROM requests WHERE created_at>=? AND status='ok' "
        "ORDER BY id DESC LIMIT 2000", (since,))
    ttfts = [_num(r["ttft_ms"]) for r in rows if r["ttft_ms"]]
    totals = [_num(r["total_ms"]) for r in rows if r["total_ms"]]
    series = await fetch_all(
        "SELECT CAST((created_at-?)/3600 AS INTEGER) h, COUNT(*) c, SUM(total_tokens) tk, SUM(cost) cost "
        "FROM requests WHERE created_at>=? GROUP BY h ORDER BY h", (since, since))
    models = await fetch_all(
        "SELECT model, COUNT(*) c, SUM(total_tokens) tk, SUM(cost) cost, AVG(ttft_ms) ttft "
        "FROM requests WHERE created_at>=? GROUP BY model ORDER BY c DESC LIMIT 8", (since,))
    return {
        "days": days,
        "count": count,
        "tokens": int(total.get("tk") or 0),
        "cost": round(_num(total.get("cost")), 6),
        "errors": int(total.get("err") or 0),
        "error_rate": round((total.get("err") or 0) * 100 / count, 2) if count else 0,
        "local_calls": int(total.get("local_c") or 0),
        "cloud_calls": count - int(total.get("local_c") or 0),
        "cache_hits": int(total.get("cache_c") or 0),
        "p50_ttft": _pct(ttfts, 50), "p95_ttft": _pct(ttfts, 95),
        "p50_total": _pct(totals, 50), "p95_total": _pct(totals, 95),
        "series": [{**s, "t": int(since + ((s.get("h") or 0) + 1) * 3600 - 1)} for s in series],
        "models": models,
    }


# ------------------------------------------------------------------ 调用记录
@router.get("/requests")
async def list_requests(page: int = 1, size: int = 20, status: str = "", model: str = "",
                        provider: str = "", q: str = "", user: dict = Depends(admin_user)):
    size = max(1, min(size, 200))
    where, params = ["1=1"], []
    if status:
        where.append("status=?")
        params.append(status)
    if model:
        where.append("model LIKE ?")
        params.append(f"%{model}%")
    if provider:
        where.append("provider=?")
        params.append(provider)
    if q:
        q = q.strip()
        only_conv = q[1:] if q.startswith("#") and q[1:].isdigit() else (q if q.isdigit() else "")
        if only_conv:
            where.append("CAST(conversation_id AS TEXT) = ?")
            params += [only_conv]
        else:
            where.append("(prompt_rendered LIKE ? OR error LIKE ? OR trace_id LIKE ? "
                         "OR CAST(conversation_id AS TEXT) LIKE ? "
                         "OR EXISTS(SELECT 1 FROM conversations c WHERE c.id=requests.conversation_id "
                         "AND c.title LIKE ?) "
                         "OR EXISTS(SELECT 1 FROM users u WHERE u.id=requests.user_id "
                         "AND u.username LIKE ?))")
            params += [f"%{q}%"] * 6
    sql = " AND ".join(where)
    total = await fetch_one(f"SELECT COUNT(*) c FROM requests WHERE {sql}", params)
    rows = await fetch_all(
        f"SELECT id,trace_id,user_id,conversation_id,provider,model,status,error,"
        f"(SELECT u.username FROM users u WHERE u.id=requests.user_id) username,"
        f"(SELECT c.title FROM conversations c WHERE c.id=requests.conversation_id) conversation_title,"
        f"prompt_tokens,completion_tokens,total_tokens,tokens_estimated,cost,"
        f"ttft_ms,total_ms,queue_ms,cache_hit,tokens_estimated,created_at,"
        f"(SELECT attrs_json FROM spans s WHERE s.request_id=requests.id AND s.kind='llm' "
        f"ORDER BY s.id LIMIT 1) llm_attrs,"
        f"(SELECT COUNT(*) FROM spans s WHERE s.request_id=requests.id AND s.kind='tool') tool_count "
        f"FROM requests WHERE {sql} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size])
    return {"items": rows, "total": (total or {}).get("c", 0), "page": page, "size": size}


@router.get("/requests/{rid}")
async def request_detail(rid: int, user: dict = Depends(admin_user)):
    row = await fetch_one(
        "SELECT *,(SELECT u.username FROM users u WHERE u.id=requests.user_id) username,"
        "(SELECT c.title FROM conversations c WHERE c.id=requests.conversation_id) conversation_title "
        "FROM requests WHERE id=?", (rid,))
    if not row:
        raise HTTPException(404, "记录不存在")
    spans = await fetch_all("SELECT * FROM spans WHERE request_id=? ORDER BY id", (rid,))
    return {"request": row, "spans": spans}


@router.delete("/requests")
async def clear_requests(before_days: int = Query(7, ge=0, le=365), user: dict = Depends(admin_user)):
    cutoff = time.time() - before_days * 86400
    await execute("DELETE FROM requests WHERE created_at<?", (cutoff,))
    await execute("DELETE FROM spans WHERE created_at<?", (cutoff,))
    return {"ok": True, "cutoff": cutoff}


# ------------------------------------------------------------------ 供应商
class ProviderBody(BaseModel):
    name: str
    kind: str = "openai"
    base_url: str
    api_key: str = ""
    models: str = ""
    price_in: float = 0
    price_out: float = 0
    timeout: float = 120
    enabled: bool = True
    note: str = ""


class ProviderPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: str | None = None
    price_in: float | None = None
    price_out: float | None = None
    timeout: float | None = None
    enabled: bool | None = None
    note: str | None = None


@router.get("/providers")
async def list_providers(user: dict = Depends(admin_user)):
    rows = await fetch_all("SELECT * FROM providers ORDER BY id")
    for r in rows:
        cipher = r.pop("api_key", "")
        try:
            r["api_key_masked"] = _mask(secrets_store.decrypt(cipher))
        except Exception:
            r["api_key_masked"] = "****（无法解密）"
    return {"items": rows}


@router.post("/providers")
async def create_provider(body: ProviderBody, user: dict = Depends(admin_user)):
    exists = await fetch_one("SELECT id FROM providers WHERE name=?", (body.name,))
    if exists:
        raise HTTPException(400, "同名供应商已存在")
    await execute(
        "INSERT INTO providers(name,kind,base_url,api_key,models,price_in,price_out,timeout,enabled,note,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (body.name, body.kind, body.base_url.rstrip("/"), secrets_store.encrypt(body.api_key), body.models,
         body.price_in, body.price_out, body.timeout, 1 if body.enabled else 0,
         body.note, time.time()))
    return {"ok": True}


@router.patch("/providers/{pid}")
async def update_provider(pid: int, body: ProviderPatch, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM providers WHERE id=?", (pid,))
    if not row:
        raise HTTPException(404, "供应商不存在")
    data = body.model_dump(exclude_none=True)
    if "api_key" in data and data["api_key"].startswith("****"):
        data.pop("api_key")
    if "api_key" in data:
        data["api_key"] = secrets_store.encrypt(data["api_key"])
    if "enabled" in data:
        data["enabled"] = 1 if data["enabled"] else 0
    if not data:
        return {"ok": True}
    sets = ", ".join(f"{k}=?" for k in data)
    await execute(f"UPDATE providers SET {sets} WHERE id=?", list(data.values()) + [pid])
    return {"ok": True}


@router.delete("/providers/{pid}")
async def delete_provider(pid: int, user: dict = Depends(admin_user)):
    await execute("DELETE FROM providers WHERE id=?", (pid,))
    return {"ok": True}


@router.post("/providers/{pid}/test")
async def test_provider(pid: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM providers WHERE id=?", (pid,))
    if not row:
        raise HTTPException(404, "供应商不存在")
    base = row["base_url"].rstrip("/")
    key_plain = secrets_store.decrypt(row["api_key"])
    headers = {"Authorization": f"Bearer {key_plain}"} if key_plain else {}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{base}/models", headers=headers)
        ms = int((time.monotonic() - t0) * 1000)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
        return {"ok": r.status_code < 400, "status": r.status_code, "ms": ms,
                "models": models[:30], "detail": "" if r.status_code < 400 else r.text[:200]}
    except Exception as e:
        return {"ok": False, "status": 0, "ms": int((time.monotonic() - t0) * 1000), "detail": str(e)[:200]}


# ------------------------------------------------------------------ 云端补强
class AssistBody(BaseModel):
    enabled: bool = True
    provider_id: int = 0
    model: str = Field(default="", max_length=120)
    auto_threshold: int = Field(default=4, ge=0, le=10)
    daily_tokens: int = Field(default=150000, ge=0, le=1_000_000_000)
    allow_attachments: bool = False
    open_to_all: bool = True
    sensitive_words: str = Field(default="", max_length=500)


@router.get("/assist")
async def get_assist(user: dict = Depends(admin_user)):
    cfg = load_config()
    providers = await fetch_all("SELECT * FROM providers ORDER BY id")
    since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    usage = await fetch_one(
        "SELECT COUNT(*) n, COALESCE(SUM(tokens_in+tokens_out),0) t FROM assist_logs "
        "WHERE created_at>=?", (since,)) or {}
    logs = await fetch_all(
        "SELECT provider,model,reason,tokens_in,tokens_out,latency_ms,status,error,created_at "
        "FROM assist_logs ORDER BY id DESC LIMIT 12")
    target = await assist.target(cfg)
    return {
        "enabled": bool(cfg.get("assist_enabled", True)),
        "provider_id": int(cfg.get("assist_provider_id") or 0),
        "model": str(cfg.get("assist_model") or ""),
        "auto_threshold": int(cfg.get("assist_auto_threshold") or 0),
        "daily_tokens": int(cfg.get("assist_daily_tokens") or 0),
        "allow_attachments": bool(cfg.get("assist_allow_attachments")),
        "open_to_all": bool(cfg.get("assist_open_to_all", True)),
        "sensitive_words": str(cfg.get("assist_sensitive_words") or ""),
        "active": bool(target),
        "active_provider": (target or {}).get("provider") or "",
        "active_model": (target or {}).get("model") or "",
        "providers": [{"id": int(p["id"]), "name": p["name"],
                       "base_url": p["base_url"], "models": p["models"],
                       "enabled": bool(p["enabled"])} for p in providers],
        "usage": {"requests": int(usage.get("n") or 0), "tokens": int(usage.get("t") or 0)},
        "logs": logs,
    }


@router.put("/assist")
async def put_assist(body: AssistBody, user: dict = Depends(admin_user)):
    if body.provider_id:
        row = await fetch_one("SELECT * FROM providers WHERE id=?", (body.provider_id,))
        if not row:
            raise HTTPException(404, "供应商不存在")
        if not row["enabled"]:
            raise HTTPException(400, "供应商已停用，请先启用")
        models = [m.strip() for m in str(row["models"] or "").split(",") if m.strip()]
        if not body.model and not models:
            raise HTTPException(400, "这个供应商还没有模型，请先到供应商页补齐")
    cfg = load_config()
    cfg.update({
        "assist_enabled": bool(body.enabled),
        "assist_provider_id": int(body.provider_id),
        "assist_model": body.model.strip(),
        "assist_auto_threshold": int(body.auto_threshold),
        "assist_daily_tokens": int(body.daily_tokens),
        "assist_allow_attachments": bool(body.allow_attachments),
        "assist_open_to_all": bool(body.open_to_all),
        "assist_sensitive_words": body.sensitive_words.strip(),
    })
    save_config(cfg)
    await audit(user, "assist.update", "cloud_assist",
                f"provider={body.provider_id} model={body.model} daily={body.daily_tokens}")
    target = await assist.target(load_config())
    return {"ok": True, "active": bool(target),
            "active_provider": (target or {}).get("provider") or "",
            "active_model": (target or {}).get("model") or ""}


# ------------------------------------------------------------------ 路由
class RouteBody(BaseModel):
    name: str
    strategy: str = "local_first"
    provider_id: int | None = None
    model_map: str = "{}"
    fallback: str = "[]"
    enabled: bool = True
    note: str = ""


@router.get("/routes")
async def list_routes(user: dict = Depends(admin_user)):
    rows = await fetch_all("SELECT * FROM routes ORDER BY id")
    return {"items": rows}


@router.post("/routes")
async def create_route(body: RouteBody, user: dict = Depends(admin_user)):
    try:
        json.loads(body.model_map); json.loads(body.fallback)
    except Exception:
        raise HTTPException(400, "model_map / fallback 必须是合法 JSON")
    await execute(
        "INSERT INTO routes(name,strategy,provider_id,model_map,fallback,enabled,note,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (body.name, body.strategy, body.provider_id, body.model_map, body.fallback,
         1 if body.enabled else 0, body.note, time.time()))
    return {"ok": True}


@router.delete("/routes/{rid}")
async def delete_route(rid: int, user: dict = Depends(admin_user)):
    await execute("DELETE FROM routes WHERE id=?", (rid,))
    return {"ok": True}


# ------------------------------------------------------------------ 缓存 / 实验（占位，M4 用）
@router.get("/cache/stats")
async def cache_stats(user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT COUNT(*) c, SUM(hits) h FROM cache_entries") or {}
    return {"entries": row.get("c", 0), "hits": row.get("h", 0)}


# ------------------------------------------------------------------ 审计日志
@router.get("/audit")
async def audit_logs(
    q: str = "",
    action: str = "",
    status: str = "",
    days: int = Query(0, ge=0, le=365),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(admin_user),
):
    """管理员操作日志：谁在什么时候改了什么，失败也留痕。"""
    where: list[str] = []
    args: list[Any] = []
    if days:
        where.append("ts>=?")
        args.append(time.time() - days * 86400)
    if action:
        where.append("action LIKE ?")
        args.append(f"{action}%")
    if status:
        where.append("status=?")
        args.append(status)
    if q:
        like = f"%{q}%"
        where.append("(username LIKE ? OR action LIKE ? OR target LIKE ? OR detail LIKE ? OR ip LIKE ?)")
        args.extend([like, like, like, like, like])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = await fetch_one(f"SELECT COUNT(*) c FROM audit_logs{clause}", tuple(args))
    rows = await fetch_all(
        f"SELECT id,ts,user_id,username,action,target,detail,status,ip "
        f"FROM audit_logs{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        tuple(args) + (limit, offset))
    return {"items": rows, "total": (total or {}).get("c", 0), "limit": limit, "offset": offset}


# ------------------------------------------------------------------ 自定义技能
SKILL_ICONS = {"spark", "list", "translate", "edit", "code", "file", "plan"}


class SkillBody(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    hint: str = Field(default="", max_length=40)
    icon: str = "spark"
    prompt: str = Field(min_length=1, max_length=3000)
    enabled: bool = True
    sort: int = 0


class SkillPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20)
    hint: str | None = Field(default=None, max_length=40)
    icon: str | None = None
    prompt: str | None = Field(default=None, min_length=1, max_length=3000)
    enabled: bool | None = None
    sort: int | None = None


def _check_skill_name(name: str) -> str:
    value = " ".join(name.split())
    if not value:
        raise HTTPException(400, "技能名称不能为空")
    if value in {s["name"] for s in skills.SKILLS}:
        raise HTTPException(400, "技能名称和内置技能重复")
    return value


def _check_icon(icon: str) -> str:
    if icon not in SKILL_ICONS:
        raise HTTPException(400, "图标不在可选范围内")
    return icon


@router.get("/skills")
async def list_skills(user: dict = Depends(admin_user)):
    return {"items": skills.admin_list(), "icons": sorted(SKILL_ICONS)}


@router.post("/skills")
async def create_skill(body: SkillBody, user: dict = Depends(admin_user)):
    name = _check_skill_name(body.name)
    if await fetch_one("SELECT id FROM custom_skills WHERE name=?", (name,)):
        raise HTTPException(400, "同名技能已存在")
    now = time.time()
    sid = await execute(
        "INSERT INTO custom_skills(name,hint,icon,prompt,enabled,sort,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (name, body.hint.strip(), _check_icon(body.icon), body.prompt.strip(),
         1 if body.enabled else 0, body.sort, now, now))
    skills.reload_custom()
    await audit(user, "skill.create", name, f"id={sid}")
    return {"ok": True, "id": sid}


@router.patch("/skills/{sid}")
async def patch_skill(sid: int, body: SkillPatch, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM custom_skills WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "自定义技能不存在")
    data: dict[str, Any] = {}
    if body.name is not None:
        name = _check_skill_name(body.name)
        if await fetch_one("SELECT id FROM custom_skills WHERE name=? AND id<>?", (name, sid)):
            raise HTTPException(400, "同名技能已存在")
        data["name"] = name
    if body.hint is not None:
        data["hint"] = body.hint.strip()
    if body.icon is not None:
        data["icon"] = _check_icon(body.icon)
    if body.prompt is not None:
        data["prompt"] = body.prompt.strip()
    if body.enabled is not None:
        data["enabled"] = 1 if body.enabled else 0
    if body.sort is not None:
        data["sort"] = body.sort
    if not data:
        return {"ok": True}
    data["updated_at"] = time.time()
    sets = ", ".join(f"{k}=?" for k in data)
    await execute(f"UPDATE custom_skills SET {sets} WHERE id=?", list(data.values()) + [sid])
    skills.reload_custom()
    await audit(user, "skill.update", row["name"], str(data)[:200])
    return {"ok": True}


@router.delete("/skills/{sid}")
async def delete_skill(sid: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT name FROM custom_skills WHERE id=?", (sid,))
    if not row:
        raise HTTPException(404, "自定义技能不存在")
    await execute("DELETE FROM custom_skills WHERE id=?", (sid,))
    skills.reload_custom()
    await audit(user, "skill.delete", row["name"], f"id={sid}")
    return {"ok": True}


@router.get("/org")
async def get_org(user: dict = Depends(admin_user)):
    cfg = load_config()
    data = branding.public()
    for key in ("org_domain", "org_industry", "org_size",
                "org_contact_name", "org_contact_email"):
        data[key] = cfg.get(key) or ""
    data["brand_logo_name"] = Path(str(cfg.get("brand_logo") or "")).name
    data["brand_copyright"] = cfg.get("brand_copyright") or ""
    return data


@router.put("/org")
async def put_org(body: OrgBody, user: dict = Depends(admin_user)):
    fields = body.model_dump(exclude_unset=True)
    if fields.get("org_contact_email") and "@" not in str(fields["org_contact_email"]):
        raise HTTPException(400, "联系人邮箱格式不正确")
    cfg = load_config()
    for k, v in fields.items():
        if isinstance(v, str):
            v = v.strip()
        cfg[k] = v
    cfg["org_name"] = str(cfg["org_name"]).strip() or "本地 AI 工作台"
    cfg["org_short_name"] = str(cfg["org_short_name"]).strip() or cfg["org_name"]
    cfg["watermark_text"] = str(cfg["watermark_text"]).strip() or "{user} · {org} · 内部资料"
    cfg["brand_primary"] = branding.normalize_color(cfg.get("brand_primary"))
    cfg["brand_icp_url"] = branding.safe_link(
        cfg.get("brand_icp_url"), "https://beian.miit.gov.cn/")
    cfg["brand_police_url"] = branding.safe_link(
        cfg.get("brand_police_url"), "https://beian.mps.gov.cn/#/query/webSearch")
    save_config(cfg)
    await audit(user, "org.update", cfg["org_name"],
                f"icp={bool(cfg.get('brand_icp'))} watermark={bool(cfg['watermark_enabled'])}")
    return {"ok": True, "branding": branding.public()}


@router.post("/org/logo")
async def upload_org_logo(file: UploadFile = File(...), user: dict = Depends(admin_user)):
    raw = await file.read()
    try:
        result = branding.save_logo(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "org.logo", file.filename or "logo", f"size={len(raw)}")
    return {"ok": True, **result}


@router.delete("/org/logo")
async def delete_org_logo(user: dict = Depends(admin_user)):
    branding.remove_logo()
    await audit(user, "org.logo.delete", "Logo", "恢复默认图标")
    return {"ok": True}


# ------------------------------------------------------------------ 内容安全
class ModerationBody(BaseModel):
    enabled: bool = False
    input_action: str = "block"
    output_action: str = "replace"
    replace_with: str = Field(default="***", max_length=20)
    min_chars: int = Field(default=1, ge=1, le=20)


class WordBody(BaseModel):
    word: str = Field(min_length=1, max_length=80)
    category: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=200)
    enabled: bool = True


class WordPatch(BaseModel):
    word: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class WordBulkBody(BaseModel):
    text: str = Field(min_length=1, max_length=60000)
    category: str = Field(default="", max_length=40)
    enabled: bool = True


def _word(value: str) -> str:
    word = " ".join((value or "").split())
    if not word:
        raise HTTPException(400, "敏感词不能为空")
    if len(word) > 80:
        raise HTTPException(400, "单个敏感词不能超过 80 字")
    return word


@router.get("/moderation")
async def get_moderation(
    word_q: str = "",
    direction: str = "",
    hit_limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(admin_user),
):
    cfg = moderation.settings()
    stats = await fetch_one(
        "SELECT COUNT(*) total, SUM(enabled) enabled FROM sensitive_words") or {}
    today = await fetch_one(
        "SELECT COUNT(*) c FROM moderation_hits WHERE created_at>=?",
        (time.time() - 86400,)) or {}
    where = ""
    args: list[Any] = []
    if word_q:
        where = " WHERE word LIKE ? OR category LIKE ? OR note LIKE ?"
        like = f"%{word_q}%"
        args = [like, like, like]
    words = await fetch_all(
        f"SELECT id,word,category,enabled,note,created_at FROM sensitive_words{where} "
        "ORDER BY enabled DESC, category, LENGTH(word), id LIMIT 2000", tuple(args))
    hit_where = " WHERE direction=?" if direction in ("input", "output") else ""
    hit_args: list[Any] = [direction] if hit_where else []
    hits = await fetch_all(
        f"SELECT id,user_id,username,direction,action,words,snippet,model,conversation_id,"
        f"created_at FROM moderation_hits{hit_where} ORDER BY id DESC LIMIT ?",
        tuple(hit_args) + (hit_limit,))
    for h in hits:
        try:
            h["words"] = json.loads(h.get("words") or "[]")
        except Exception:
            h["words"] = []
    return {
        "settings": cfg,
        "stats": {"words": int(stats.get("total") or 0),
                  "enabled_words": int(stats.get("enabled") or 0),
                  "hits_24h": int(today.get("c") or 0)},
        "words": words,
        "hits": hits,
    }


@router.put("/moderation")
async def put_moderation(body: ModerationBody, user: dict = Depends(admin_user)):
    input_action = moderation.normalize_action(body.input_action, "")
    output_action = moderation.normalize_action(body.output_action, "")
    if not input_action or not output_action:
        raise HTTPException(400, "动作只能是 block、replace 或 warn")
    cfg = load_config()
    cfg.update({
        "moderation_enabled": bool(body.enabled),
        "moderation_input_action": input_action,
        "moderation_output_action": output_action,
        "moderation_replace": body.replace_with.strip() or "***",
        "moderation_min_chars": max(1, min(int(body.min_chars), 20)),
    })
    save_config(cfg)
    moderation.invalidate()
    await audit(user, "moderation.update", "",
                f"enabled={cfg['moderation_enabled']} in={input_action} out={output_action}")
    return {"ok": True, "settings": moderation.settings()}


@router.post("/moderation/words")
async def add_moderation_word(body: WordBody, user: dict = Depends(admin_user)):
    word = _word(body.word)
    exists = await fetch_one("SELECT id FROM sensitive_words WHERE LOWER(word)=LOWER(?)", (word,))
    if exists:
        raise HTTPException(400, "这个敏感词已经在词库里")
    await execute(
        "INSERT INTO sensitive_words(word,category,enabled,note,created_at) VALUES(?,?,?,?,?)",
        (word, body.category.strip(), 1 if body.enabled else 0, body.note.strip(), time.time()))
    moderation.invalidate()
    await audit(user, "moderation.word.add", word, body.category)
    return {"ok": True}


@router.post("/moderation/words/bulk")
async def bulk_moderation_words(body: WordBulkBody, user: dict = Depends(admin_user)):
    raw = body.text.replace("；", "\n").replace(";", "\n").replace("，", "\n").replace(",", "\n")
    candidates = [_word(x) for x in raw.splitlines() if x.strip()]
    created, skipped, errors = 0, 0, []
    for word in dict.fromkeys(candidates):
        try:
            if await fetch_one("SELECT id FROM sensitive_words WHERE LOWER(word)=LOWER(?)", (word,)):
                skipped += 1
                continue
            await execute(
                "INSERT INTO sensitive_words(word,category,enabled,note,created_at) VALUES(?,?,?,?,?)",
                (word, body.category.strip(), 1 if body.enabled else 0, "", time.time()))
            created += 1
        except Exception as exc:
            errors.append({"word": word, "error": str(exc)[:120]})
    moderation.invalidate()
    await audit(user, "moderation.word.bulk", body.category,
                f"created={created} skipped={skipped} errors={len(errors)}")
    return {"created": created, "skipped": skipped, "errors": errors}


@router.patch("/moderation/words/{wid}")
async def patch_moderation_word(wid: int, body: WordPatch, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM sensitive_words WHERE id=?", (wid,))
    if not row:
        raise HTTPException(404, "敏感词不存在")
    values: dict[str, Any] = {}
    if body.word is not None:
        word = _word(body.word)
        dup = await fetch_one(
            "SELECT id FROM sensitive_words WHERE LOWER(word)=LOWER(?) AND id<>?", (word, wid))
        if dup:
            raise HTTPException(400, "这个敏感词已经在词库里")
        values["word"] = word
    if body.category is not None:
        values["category"] = body.category.strip()
    if body.note is not None:
        values["note"] = body.note.strip()
    if body.enabled is not None:
        values["enabled"] = 1 if body.enabled else 0
    if values:
        sets = ",".join(f"{k}=?" for k in values)
        await execute(f"UPDATE sensitive_words SET {sets} WHERE id=?", tuple(values.values()) + (wid,))
    moderation.invalidate()
    await audit(user, "moderation.word.update", values.get("word", row["word"]))
    return {"ok": True}


@router.delete("/moderation/words/{wid}")
async def delete_moderation_word(wid: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT word FROM sensitive_words WHERE id=?", (wid,))
    if not row:
        raise HTTPException(404, "敏感词不存在")
    await execute("DELETE FROM sensitive_words WHERE id=?", (wid,))
    moderation.invalidate()
    await audit(user, "moderation.word.delete", row["word"])
    return {"ok": True}


@router.delete("/moderation/hits")
async def clear_moderation_hits(user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT COUNT(*) c FROM moderation_hits") or {}
    await execute("DELETE FROM moderation_hits")
    await audit(user, "moderation.hits.clear", "", f"deleted={row.get('c', 0)}")
    return {"ok": True, "deleted": int(row.get("c") or 0)}
