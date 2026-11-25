"""前台功能注册表：管理员控制用户端显示哪些入口，并配置每个入口的图标。

设计口径：
- 展示开关只负责“前台是否显示”，不改变用户权限，也不删除已有数据。
- 联网、知识库、资料库、长期记忆本来就有能力总开关，这里直接复用，
  不另造一套状态，避免控制台两处开关互相打架。
- 图标支持内置图标键和图标库里的自定义图片；自定义图片以 data URL 存储，
  用户端只拿已开启功能需要的图标，不会暴露未启用入口。
"""
from __future__ import annotations

import time
from typing import Any

from ..config import load_config, save_config
from ..db import execute, fetch_all, fetch_one

GROUP_DEFS: list[dict[str, Any]] = [
    {"key": "chat", "label": "对话增强", "tone": "blue"},
    {"key": "data", "label": "资料与记忆", "tone": "green"},
    {"key": "tools", "label": "效率工具", "tone": "amber"},
    {"key": "collab", "label": "协作与接入", "tone": "purple"},
]

PRESET_ICONS: list[dict[str, str]] = [
    {"key": "spark", "label": "灵感"},
    {"key": "book", "label": "资料"},
    {"key": "search", "label": "搜索"},
    {"key": "file", "label": "文档"},
    {"key": "paperclip", "label": "附件"},
    {"key": "brain", "label": "智能"},
    {"key": "grid", "label": "工作台"},
    {"key": "clock", "label": "定时"},
    {"key": "download", "label": "下载"},
    {"key": "share", "label": "共享"},
    {"key": "help", "label": "服务"},
    {"key": "key", "label": "密钥"},
    {"key": "list", "label": "列表"},
    {"key": "code", "label": "代码"},
    {"key": "plan", "label": "计划"},
    {"key": "user", "label": "成员"},
    {"key": "shield", "label": "安全"},
    {"key": "monitor", "label": "观测"},
]
PRESET_KEYS = {x["key"] for x in PRESET_ICONS}
TONES = {"blue", "green", "amber", "purple", "gray", "teal"}


def _def(key: str, name: str, group: str, description: str, icon: str, tone: str,
         surfaces: list[str], *, source: str = "entry", config_key: str = "",
         depends_on: str = "", default_on: bool = True, switch_hint: str = "") -> dict[str, Any]:
    return {
        "key": key, "name": name, "group": group, "description": description,
        "icon": icon, "tone": tone, "surfaces": surfaces,
        "source": source, "config_key": config_key,
        "depends_on": depends_on, "default_on": default_on,
        "switch_hint": switch_hint or (
            "同时控制能力和前台入口" if source == "config" else "仅隐藏前台入口，数据保留"
        ),
    }


FEATURE_DEFS: list[dict[str, Any]] = [
    _def("skills", "技能与插件", "chat",
         "输入框技能、侧栏插件入口与工作台技能页。", "spark", "blue",
         ["输入框 · 技能", "侧栏 · 插件技能", "工作台 · 技能"]),
    _def("web", "联网检索", "chat",
         "发送前检索实时网页，并在回答里保留来源。", "search", "teal",
         ["输入框 · 联网", "回答 · 来源"], source="config",
         config_key="websearch_enabled"),
    _def("docgen", "文档生成", "chat",
         "把回答整理成 Word、Excel、PPT、PDF 等可下载文件。", "file", "amber",
         ["输入框 · 格式", "回答 · 文件卡片"]),
    _def("attach", "附件上传与解析", "chat",
         "上传文档、图片并做解析或 OCR，随消息一起理解。", "paperclip", "green",
         ["输入框 · 附件", "上传 · 解析"]),
    _def("agent", "智能体选择", "chat",
         "在顶部切换智能体；关闭后仍可使用通用助手。", "brain", "purple",
         ["顶部 · 智能体"]),
    _def("library", "资料库", "data",
         "长期保存的资料，可挑选后随每条消息反复使用。", "book", "green",
         ["输入框 · 资料库", "设置 · 资料库"], source="config",
         config_key="library_enabled"),
    _def("kb", "个人知识库", "data",
         "检索本机和个人知识库资料，再交给模型回答。", "book", "blue",
         ["设置 · 知识库", "回答 · 引用"], source="config",
         config_key="kb_enabled"),
    _def("memory", "长期记忆", "data",
         "跨对话保存偏好，并在相关问题时参考。", "brain", "purple",
         ["设置 · 记忆"], source="config", config_key="memory_enabled"),
    _def("workbench", "工作台", "tools",
         "工作台总入口、当前工作台条和推荐模板。", "grid", "amber",
         ["侧栏 · 工作台", "当前工作台", "工作台面板"]),
    _def("schedule", "定时任务", "tools",
         "工作台里的定时任务页；已有任务和记录保留。", "clock", "blue",
         ["工作台 · 定时任务"], depends_on="workbench"),
    _def("files", "生成文件", "tools",
         "工作台里的生成文件列表；已有文件保留。", "download", "green",
         ["工作台 · 生成文件"], depends_on="workbench"),
    _def("collab", "小队与共享", "collab",
         "小队、共享会话和顶部“分享当前对话”。", "share", "purple",
         ["侧栏 · 小队与共享", "顶部 · 分享"]),
    _def("desk", "服务台", "collab",
         "用户提交问题工单，查看处理进度。", "help", "blue",
         ["侧栏 · 服务台"]),
    _def("api_access", "API 接入", "collab",
         "设置里的 API 密钥与调用说明。", "key", "gray",
         ["设置 · API"]),
    _def("data_export", "数据导出", "collab",
         "设置里的账号数据、对话与文件导出。", "download", "teal",
         ["设置 · 数据"]),
]

FEATURE_MAP = {f["key"]: f for f in FEATURE_DEFS}


def _tone(value: str, fallback: str) -> str:
    return value if value in TONES else fallback


def _clean_icon_key(value: str, fallback: str = "spark") -> str:
    return value if value in PRESET_KEYS else fallback


async def seed_defaults(cfg: dict[str, Any] | None = None) -> int:
    """补齐缺失的功能行；不覆盖管理员已有的开关、图标和默认值。"""
    cfg = cfg or load_config()
    created = 0
    for f in FEATURE_DEFS:
        enabled = bool(cfg.get(f["config_key"], False)) if f["source"] == "config" else bool(f["default_on"])
        existing = await fetch_one("SELECT key FROM front_features WHERE key=?", (f["key"],))
        if existing:
            continue
        await execute(
            "INSERT INTO front_features(key,enabled,icon_key,icon_tone,icon_id,updated_at,updated_by) "
            "VALUES(?,?,?,?,?,?,?)",
            (f["key"], 1 if enabled else 0, f["icon"], f["tone"], 0, 0, ""),
        )
        created += 1
    return created


async def revision() -> int:
    row = await fetch_one("SELECT value FROM settings WHERE key='front_rev'")
    try:
        return int(row["value"]) if row else 1
    except Exception:
        return 1


async def _bump_rev() -> int:
    rev = int(time.time())
    current = await revision()
    rev = max(rev, current + 1)
    await execute(
        "INSERT INTO settings(key,value) VALUES('front_rev',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(rev),))
    return rev


async def _icons_map() -> dict[int, dict[str, Any]]:
    rows = await fetch_all("SELECT id,name,mime,data,created_at,created_by FROM front_icons")
    return {int(r["id"]): r for r in rows}


def _row_state(f: dict[str, Any], row: dict[str, Any] | None, cfg: dict[str, Any]) -> dict[str, Any]:
    row = row or {}
    enabled = bool(cfg.get(f["config_key"], False)) if f["source"] == "config" else bool(row.get("enabled", f["default_on"]))
    icon_key = _clean_icon_key(row.get("icon_key") or f["icon"], f["icon"])
    tone = _tone(row.get("icon_tone") or f["tone"], f["tone"])
    return {
        "key": f["key"], "name": f["name"], "group": f["group"],
        "description": f["description"], "surfaces": f["surfaces"],
        "icon_key": icon_key, "icon_tone": tone, "icon_id": int(row.get("icon_id") or 0),
        "enabled": enabled, "raw_enabled": enabled,
        "source": f["source"], "config_key": f["config_key"],
        "depends_on": f["depends_on"], "switch_hint": f["switch_hint"],
        "updated_at": row.get("updated_at") or 0,
        "updated_by": row.get("updated_by") or "",
    }


async def catalog() -> dict[str, Any]:
    cfg = load_config()
    rows = await fetch_all("SELECT * FROM front_features")
    row_map = {r["key"]: r for r in rows}
    icons = await _icons_map()
    items: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for f in FEATURE_DEFS:
        item = _row_state(f, row_map.get(f["key"]), cfg)
        icon = icons.get(item["icon_id"])
        item["icon_data"] = icon.get("data", "") if icon else ""
        item["icon_name"] = icon.get("name", "") if icon else ""
        item["icon_missing"] = bool(item["icon_id"] and not icon)
        by_key[item["key"]] = item
        items.append(item)
    # 依赖关系：工作台关闭时，定时任务/生成文件在用户端不显示。
    for item in items:
        parent = item.get("depends_on") or ""
        blocked = ""
        if parent:
            p = by_key.get(parent)
            if not p or not p["enabled"]:
                blocked = parent
        item["blocked_by"] = blocked
        item["visible"] = bool(item["enabled"] and not blocked)
    icon_list = []
    for icon in sorted(icons.values(), key=lambda x: (-float(x.get("created_at") or 0), x["id"])):
        icon_list.append({
            "id": int(icon["id"]), "name": icon["name"], "mime": icon["mime"],
            "data": icon["data"], "created_at": icon["created_at"],
            "created_by": icon["created_by"],
            "used_by": [x["key"] for x in items if x["icon_id"] == int(icon["id"])],
        })
    return {
        "revision": await revision(),
        "groups": GROUP_DEFS,
        "presets": PRESET_ICONS,
        "items": items,
        "icons": icon_list,
        "tones": sorted(TONES),
    }


async def public_features() -> dict[str, Any]:
    data = await catalog()
    items = []
    for item in data["items"]:
        if not item["visible"]:
            continue
        items.append({
            "key": item["key"], "name": item["name"], "group": item["group"],
            "icon_key": item["icon_key"], "icon_tone": item["icon_tone"],
            "icon_data": item["icon_data"],
        })
    return {"revision": data["revision"], "items": items}


async def save_features(items: list[dict[str, Any]], username: str = "") -> dict[str, Any]:
    """保存整页状态。图标/启停变化才递增修订号，避免无意义刷新。"""
    cfg = load_config()
    old_cfg = load_config()
    changed = False
    for raw in items:
        key = str(raw.get("key") or "")
        f = FEATURE_MAP.get(key)
        if not f:
            raise ValueError(f"未知功能：{key}")
        row = await fetch_one("SELECT * FROM front_features WHERE key=?", (key,)) or {}
        enabled = raw.get("enabled")
        if enabled is None:
            enabled = bool(row.get("enabled", f["default_on"])) if f["source"] != "config" else bool(cfg.get(f["config_key"]))
        enabled = bool(enabled)
        icon_key = _clean_icon_key(str(raw.get("icon_key") or row.get("icon_key") or f["icon"]), f["icon"])
        tone = _tone(str(raw.get("icon_tone") or row.get("icon_tone") or f["tone"]), f["tone"])
        if "icon_id" in raw:
            icon_id = int(raw.get("icon_id") or 0)
        else:
            icon_id = int(row.get("icon_id") or 0)
        if icon_id:
            found = await fetch_one("SELECT id FROM front_icons WHERE id=?", (icon_id,))
            if not found:
                icon_id = 0
        old_enabled = bool(row.get("enabled", f["default_on"]))
        old_icon_key = row.get("icon_key") or f["icon"]
        old_tone = row.get("icon_tone") or f["tone"]
        old_icon_id = int(row.get("icon_id") or 0)
        if f["source"] == "config":
            if bool(cfg.get(f["config_key"])) != enabled:
                cfg[f["config_key"]] = enabled
                changed = True
        elif old_enabled != enabled:
            changed = True
        if old_icon_key != icon_key or old_tone != tone or old_icon_id != icon_id:
            changed = True
        await execute(
            "INSERT INTO front_features(key,enabled,icon_key,icon_tone,icon_id,updated_at,updated_by) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "enabled=excluded.enabled,icon_key=excluded.icon_key,icon_tone=excluded.icon_tone,"
            "icon_id=excluded.icon_id,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
            (key, 1 if enabled else 0, icon_key, tone, icon_id, time.time(), username),
        )
    if cfg != old_cfg:
        save_config(cfg)
    if changed:
        await _bump_rev()
    return await catalog()


async def add_icon(name: str, mime: str, data: str, username: str = "") -> dict[str, Any]:
    icon_id = await execute(
        "INSERT INTO front_icons(name,mime,data,created_at,created_by) VALUES(?,?,?,?,?)",
        (name, mime, data, time.time(), username),
    )
    return {"id": icon_id, "name": name, "mime": mime, "data": data}


async def delete_icon(icon_id: int) -> bool:
    row = await fetch_one("SELECT id FROM front_icons WHERE id=?", (icon_id,))
    if not row:
        return False
    await execute("UPDATE front_features SET icon_id=0 WHERE icon_id=?", (icon_id,))
    await execute("DELETE FROM front_icons WHERE id=?", (icon_id,))
    await _bump_rev()
    return True
