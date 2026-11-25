"""提示词中心：统一查看、编辑、版本恢复和拼装预览。"""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import load_config, save_config
from ..db import audit, execute, fetch_all, fetch_one
from ..security import admin_user
from ..services import docgen, prompts, skills

router = APIRouter(prefix="/api/admin/prompts", tags=["prompts"])

KIND_LABELS = {
    "core": "核心",
    "skill": "技能",
    "plugin": "功能",
    "format": "输出格式",
    "workbench": "工作台",
}
PIPELINE = [
    {"key": "core.system", "label": "基础人格", "kind": "core"},
    {"key": "skill", "label": "技能", "kind": "skill"},
    {"key": "function.kb_hint", "label": "知识库", "kind": "plugin"},
    {"key": "function.library_hint", "label": "资料库", "kind": "plugin"},
    {"key": "function.memory_rules", "label": "长期记忆", "kind": "plugin"},
    {"key": "format.docx", "label": "输出格式", "kind": "format"},
    {"key": "function.web_rules_general", "label": "联网检索", "kind": "plugin"},
]

TOGGLE_KEYS = {
    "function.kb_hint": "kb_enabled",
    "function.library_hint": "library_enabled",
    "function.memory_rules": "memory_enabled",
    "function.web_rules_general": "websearch_enabled",
    "function.web_rules_news": "websearch_enabled",
    "function.web_news_guard": "websearch_enabled",
    "function.web_skip_general": "websearch_enabled",
    "function.web_skip_doc": "websearch_enabled",
    "function.link_fallback": "websearch_enabled",
    "function.link_unreadable": "websearch_enabled",
}


class PromptBody(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    enabled: bool | None = None
    note: str = Field(default="", max_length=200)


class PreviewBody(BaseModel):
    skill_id: str = ""
    use_kb: bool = False
    use_library: bool = False
    use_memory: bool = False
    use_web: bool = False
    output_format: str = ""


def _asset_public(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta") or {}
    key = item["key"]
    return {
        "key": key,
        "name": item.get("name") or key,
        "kind": item.get("kind") or "core",
        "kind_label": KIND_LABELS.get(item.get("kind") or "", "其他"),
        "description": item.get("description") or "",
        "content": item.get("content") or "",
        "default_content": item.get("default_content") or "",
        "enabled": bool(item.get("enabled")),
        "overridden": bool(item.get("overridden")),
        "updated_at": item.get("updated_at") or 0,
        "updated_by": item.get("updated_by") or "",
        "meta": meta,
        "editable": True,
        "external": False,
    }


def _custom_asset(row: dict[str, Any], icons: list[str]) -> dict[str, Any]:
    return {
        "key": f"custom_skill.{row['id']}",
        "name": row["name"],
        "kind": "skill",
        "kind_label": "自定义技能",
        "description": row.get("hint") or "",
        "content": row.get("prompt") or "",
        "default_content": "",
        "enabled": bool(row.get("enabled")),
        "overridden": True,
        "updated_at": row.get("updated_at") or 0,
        "updated_by": "",
        "meta": {"custom_skill_id": row["id"], "skill_id": f"custom_{row['id']}",
                 "icon": row.get("icon") or "spark", "icons": icons, "sort": row.get("sort") or 0},
        "editable": True,
        "external": True,
        "external_type": "custom_skill",
    }


def _agent_asset(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": f"agent.{row['id']}",
        "name": row["name"],
        "kind": "agent",
        "kind_label": "智能体",
        "description": row.get("description") or "",
        "content": row.get("system_prompt") or "",
        "default_content": "",
        "enabled": bool(row.get("enabled")),
        "overridden": False,
        "updated_at": row.get("updated_at") or 0,
        "updated_by": "",
        "meta": {"agent_id": row["id"], "avatar": row.get("avatar") or "🤖",
                 "model": row.get("model") or "", "visibility": row.get("visibility") or "public"},
        "editable": False,
        "external": True,
        "external_type": "agent",
        "edit_hint": "在智能体页编辑",
    }


@router.get("")
async def list_prompts(user: dict = Depends(admin_user)):
    cfg = load_config()
    items = [_asset_public(x) for x in await prompts.list_assets()]
    custom = await fetch_all(
        "SELECT id,name,hint,icon,prompt,enabled,sort,updated_at FROM custom_skills ORDER BY sort,id")
    for row in custom:
        item = _custom_asset(row, sorted(set([r.get("icon") or "spark" for r in custom])))
        items.append(item)
    agents = await fetch_all(
        "SELECT id,name,description,avatar,system_prompt,model,visibility,enabled,sort,updated_at "
        "FROM agents ORDER BY sort,id")
    items.extend(_agent_asset(a) for a in agents)
    for item in items:
        toggle = TOGGLE_KEYS.get(item["key"])
        item["switch_key"] = toggle or ""
        item["switch_enabled"] = bool(cfg.get(toggle, False)) if toggle else True
        if item["key"].startswith(("function.web_", "web.")):
            item["plugin_id"] = "web"
        elif item["key"] == "function.kb_hint":
            item["plugin_id"] = "kb"
        elif item["key"] == "function.library_hint":
            item["plugin_id"] = "library"
        elif item["key"] == "function.memory_rules":
            item["plugin_id"] = "memory"
        elif item["kind"] == "format":
            item["plugin_id"] = "docgen"
        else:
            item["plugin_id"] = ""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "items": items,
        "revision": prompts.revision(),
        "counts": counts,
        "total": len(items),
        "enabled": sum(1 for x in items if x["enabled"]),
        "pipeline": PIPELINE,
        "switches": {
            "web": bool(cfg.get("websearch_enabled")),
            "kb": bool(cfg.get("kb_enabled")),
            "library": bool(cfg.get("library_enabled")),
            "memory": bool(cfg.get("memory_enabled")),
            "docgen": True,
        },
    }


@router.get("/{key}")
async def get_prompt(key: str, user: dict = Depends(admin_user)):
    if key.startswith("custom_skill."):
        sid = _int_suffix(key)
        row = await fetch_one("SELECT * FROM custom_skills WHERE id=?", (sid,))
        if not row:
            raise HTTPException(404, "技能不存在")
        item = _custom_asset(row, [])
        item["versions"] = []
        return item
    if key.startswith("agent."):
        aid = _int_suffix(key)
        row = await fetch_one("SELECT * FROM agents WHERE id=?", (aid,))
        if not row:
            raise HTTPException(404, "智能体不存在")
        item = _agent_asset(row)
        item["versions"] = []
        return item
    item = await prompts.get_asset(key)
    if not item:
        raise HTTPException(404, "提示词不存在")
    again = [x for x in await prompts.list_assets() if x["key"] == key]
    if again:
        item = {**item, **again[0]}
    public = _asset_public(item)
    public["versions"] = await prompts.versions(key)
    return public


def _int_suffix(key: str) -> int:
    try:
        return int(key.rsplit(".", 1)[1])
    except Exception:
        raise HTTPException(400, "无效的资产编号")


@router.put("/{key}")
async def save_prompt(key: str, body: PromptBody, user: dict = Depends(admin_user)):
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "提示词不能为空")
    if key.startswith("custom_skill."):
        sid = _int_suffix(key)
        row = await fetch_one("SELECT * FROM custom_skills WHERE id=?", (sid,))
        if not row:
            raise HTTPException(404, "技能不存在")
        await execute(
            "UPDATE custom_skills SET prompt=?,enabled=?,updated_at=? WHERE id=?",
            (content, int(row["enabled"] if body.enabled is None else body.enabled),
             time.time(), sid))
        skills.reload_custom()
        await audit(user, "prompt.update", key, "自定义技能提示词")
        return {"ok": True, "revision": prompts.revision(), "asset": await get_prompt(key, user)}
    if key.startswith("agent."):
        raise HTTPException(400, "智能体提示词请在智能体页编辑")
    try:
        result = await prompts.save_asset(key, content, body.enabled, user, body.note)
    except KeyError:
        raise HTTPException(404, "提示词不存在")
    if key == "core.system":
        cfg = load_config()
        cfg["system_prompt"] = content
        save_config(cfg)
    await audit(user, "prompt.update", key, (body.note or "更新提示词")[:200])
    return result


@router.post("/{key}/reset")
async def reset_prompt(key: str, user: dict = Depends(admin_user)):
    if key.startswith(("custom_skill.", "agent.")):
        raise HTTPException(400, "该资产没有可恢复的默认值")
    try:
        result = await prompts.reset_asset(key, user)
    except KeyError:
        raise HTTPException(404, "提示词不存在")
    if key == "core.system":
        cfg = load_config()
        cfg["system_prompt"] = result["asset"]["content"]
        save_config(cfg)
    await audit(user, "prompt.reset", key, "恢复默认提示词")
    return result


@router.get("/{key}/versions")
async def prompt_versions(key: str, user: dict = Depends(admin_user)):
    if not key.startswith(("custom_skill.", "agent.")):
        return {"items": await prompts.versions(key)}
    return {"items": []}


@router.post("/{key}/restore/{version}")
async def restore_prompt(key: str, version: int, user: dict = Depends(admin_user)):
    if key.startswith(("custom_skill.", "agent.")):
        raise HTTPException(400, "该资产暂不支持版本恢复")
    try:
        result = await prompts.restore_version(key, version, user)
    except KeyError:
        raise HTTPException(404, "版本不存在")
    if key == "core.system":
        cfg = load_config()
        cfg["system_prompt"] = result["asset"]["content"]
        save_config(cfg)
    await audit(user, "prompt.restore", key, f"恢复版本 {version}")
    return result


@router.post("/preview")
async def preview(body: PreviewBody, user: dict = Depends(admin_user)):
    parts: list[dict[str, Any]] = []
    core = prompts.get("core.system", "")
    if core:
        parts.append({"label": "基础人格", "content": core, "kind": "core"})
    skill = skills.get(body.skill_id) if body.skill_id else None
    if skill:
        parts.append({"label": f"技能 · {skill['name']}", "content": skill["prompt"],
                      "kind": "skill"})
    if body.use_kb:
        parts.append({"label": "知识库引用",
                      "content": prompts.get("function.kb_hint", "") + "\n【知识库资料占位：标题 + 摘要】",
                      "kind": "plugin"})
    if body.use_library:
        parts.append({"label": "资料库引用",
                      "content": prompts.get("function.library_hint", "") + "\n【资料库文档占位】",
                      "kind": "plugin"})
    if body.use_memory:
        parts.append({"label": "长期记忆",
                      "content": prompts.get("function.memory_rules", "") + "\n[记忆 1] 示例偏好",
                      "kind": "plugin"})
    fmt = docgen.resolve_format(body.output_format, "") if body.output_format else ""
    if fmt:
        parts.append({"label": f"输出格式 · {fmt}", "content": docgen.prompt_hint(fmt),
                      "kind": "format"})
    if body.use_web:
        parts.append({"label": "联网检索",
                      "content": prompts.get("function.web_rules_general", "") + "\n检索词：示例问题",
                      "kind": "plugin"})
    text = "\n\n".join(f"── {p['label']} ──\n{p['content']}" for p in parts)
    return {
        "text": text,
        "chars": len(text),
        "tokens": max(1, len(text) // 2),
        "sections": parts,
        "revision": prompts.revision(),
    }


@router.post("/reload")
async def reload_prompts(user: dict = Depends(admin_user)):
    prompts.invalidate()
    skills.reload_custom()
    await audit(user, "prompt.reload", "prompt_center", "重载提示词缓存")
    return {"ok": True, "revision": prompts.revision()}
