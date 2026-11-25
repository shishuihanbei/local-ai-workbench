"""对话技能：服务端注入提示词，前端只展示名称和说明。

内置技能固定在代码里，保证升级后不丢；管理员新建的技能存 SQLite，
启动后首次读取时加载到进程内缓存，后台增删改后立即刷新。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from ..config import DB_PATH
from . import prompts

SKILLS: list[dict[str, Any]] = [
    {
        "id": "summary",
        "name": "总结提炼",
        "hint": "长文、会议记录、聊天内容",
        "icon": "list",
        "prompt": (
            "当前启用「总结提炼」技能。请先提炼核心结论，再按要点整理；"
            "保留关键数字、时间、人员和待办事项，不要编造原文没有的信息。"
        ),
    },
    {
        "id": "translate",
        "name": "翻译",
        "hint": "中英互译，保留原意和语气",
        "icon": "translate",
        "prompt": (
            "当前启用「翻译」技能。请自动判断原文语言并翻译成另一种语言；"
            "保留专有名词、数字和格式，只输出译文，必要时再补充简短说明。"
        ),
    },
    {
        "id": "polish",
        "name": "润色改写",
        "hint": "邮件、文案、汇报材料",
        "icon": "edit",
        "prompt": (
            "当前启用「润色改写」技能。请在不改变事实和原意的前提下，"
            "让表达更清晰、正式、简洁；直接给出改写后的文本。"
        ),
    },
    {
        "id": "code",
        "name": "代码助手",
        "hint": "写代码、查问题、解释实现",
        "icon": "code",
        "prompt": (
            "当前启用「代码助手」技能。请优先给出可运行的代码，说明关键参数和运行方式；"
            "如果用户贴了报错或代码，先定位原因，再给出最小修改方案。"
        ),
    },
    {
        "id": "doc_qa",
        "name": "文件问答",
        "hint": "围绕上传的文件提取和追问",
        "icon": "file",
        "prompt": (
            "当前启用「文件问答」技能。请优先依据用户上传文件中的内容回答，"
            "引用文件名和对应段落；文件里没有的信息要明确说明，不要猜测。"
        ),
    },
    {
        "id": "plan",
        "name": "方案规划",
        "hint": "把目标拆成可执行步骤",
        "icon": "plan",
        "prompt": (
            "当前启用「方案规划」技能。请把目标拆成有顺序的步骤，标明依赖、风险和验收标准；"
            "优先给出一条可立即执行的路径。"
        ),
    },
]

BUILTIN_IDS = {s["id"] for s in SKILLS}
_CUSTOM: list[dict[str, Any]] = []
_CUSTOM_LOADED = False


def _custom_from_db() -> list[dict[str, Any]]:
    """同步读一小张表，只在首次访问和管理端变更后执行。"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id,name,hint,icon,prompt,enabled,sort FROM custom_skills "
                "ORDER BY sort,id").fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append({
            "id": f"custom_{row['id']}",
            "row_id": row["id"],
            "name": row["name"],
            "hint": row["hint"] or "",
            "icon": row["icon"] or "spark",
            "prompt": row["prompt"],
            "enabled": bool(row["enabled"]),
            "custom": True,
        })
    return items


def reload_custom() -> None:
    global _CUSTOM, _CUSTOM_LOADED
    _CUSTOM = _custom_from_db()
    _CUSTOM_LOADED = True


def _ensure_loaded() -> None:
    if not _CUSTOM_LOADED:
        reload_custom()


def _all() -> list[dict[str, Any]]:
    _ensure_loaded()
    builtin: list[dict[str, Any]] = []
    for skill in SKILLS:
        key = f"skill.{skill['id']}"
        item = {
            **skill,
            "key": key,
            "prompt": prompts.get(key, skill["prompt"]),
            "enabled": prompts.is_enabled(key, True),
            "default_prompt": skill["prompt"],
            "overridden": prompts.get(key, "") != skill["prompt"],
        }
        builtin.append(item)
    return builtin + _CUSTOM


def list_public() -> list[dict[str, str]]:
    return [
        {"id": s["id"], "name": s["name"], "hint": s["hint"], "icon": s["icon"]}
        for s in _all() if s.get("enabled", True)
    ]


def admin_list() -> list[dict[str, Any]]:
    """管理端视图：内置技能带当前提示词、默认值和覆盖状态。"""
    _ensure_loaded()
    builtin = [{**s, "row_id": None, "custom": False} for s in _all() if not s.get("custom")]
    custom = [{**s} for s in _CUSTOM]
    return builtin + custom


def get(skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id:
        return None
    for skill in _all():
        if skill["id"] == skill_id:
            if not skill.get("enabled", True):
                return None
            return skill
    return None
