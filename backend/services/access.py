"""按用户限制可调用的模型。

users.allowed_models 存储：
  "*"                    不限（管理员默认）
  JSON 数组字符串        ["7b","deepseek-chat"]
"""
from __future__ import annotations

import json

from ..db import fetch_all, fetch_one

ALL = "*"


def normalize(raw) -> str:
    """把接口传入的名单统一成落库格式。None 视为不限制。"""
    if raw is None:
        return ALL
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text == ALL:
            return ALL
        try:
            raw = json.loads(text)
        except Exception:
            raw = [x.strip() for x in text.split(",") if x.strip()]
    if isinstance(raw, (list, tuple, set)):
        items: list[str] = []
        for value in raw:
            name = str(value or "").strip()
            if not name:
                continue
            if name == ALL:
                return ALL
            if name not in items:
                items.append(name)
            if len(items) >= 120:
                break
        return json.dumps(items, ensure_ascii=False) if items else json.dumps([])
    return ALL


def parse(raw) -> set[str] | None:
    """返回允许集合；None 表示不限制。"""
    if not raw or str(raw).strip() in ("", ALL):
        return None
    if isinstance(raw, (list, tuple, set)):
        items = [str(x).strip() for x in raw if str(x).strip()]
        return None if ALL in items else set(items)
    try:
        value = json.loads(str(raw))
    except Exception:
        value = [x.strip() for x in str(raw).split(",") if x.strip()]
    if isinstance(value, str):
        return None if value.strip() in ("", ALL) else {value.strip()}
    items = {str(x).strip() for x in value if str(x).strip()} if isinstance(value, (list, tuple, set)) else set()
    return None if ALL in items else items


async def allowed_for(user: dict) -> set[str] | None:
    """当前用户允许的模型集合；管理员或 '*' 返回 None。"""
    if user.get("role") == "admin":
        return None
    row = await fetch_one("SELECT allowed_models FROM users WHERE id=?", (user["id"],))
    return parse(row["allowed_models"] if row else ALL)


async def _names(model: str) -> set[str]:
    """请求里的模型名可能写成 key 或 alias，统一展开。"""
    names = {str(model or "").strip()} - {""}
    if not names:
        return names
    row = await fetch_one("SELECT key,alias FROM models WHERE key=? OR alias=?", (model, model))
    if row:
        names.add(row["key"])
        if row["alias"]:
            names.add(row["alias"])
    return names


async def can_use(user: dict, model: str) -> bool:
    allowed = await allowed_for(user)
    if allowed is None:
        return True
    return bool(await _names(model) & allowed)


async def first_model(user: dict) -> str | None:
    """受限用户未指定模型时，取名单里第一个可用模型。

    返回 None 表示不限制；返回空字符串表示名单为空、没有可用模型。
    """
    from ..config import load_config
    allowed = await allowed_for(user)
    if allowed is None:
        return None
    if not allowed:
        return ""
    local_enabled = bool(load_config().get("local_enabled", True))
    if local_enabled:
        rows = await fetch_all("SELECT key,alias FROM models ORDER BY sort,key")
        for row in rows:
            if row["key"] in allowed or (row["alias"] and row["alias"] in allowed):
                return row["key"]
    for p in await fetch_all("SELECT models FROM providers WHERE enabled=1 ORDER BY id"):
        for name in [x.strip() for x in (p["models"] or "").split(",") if x.strip()]:
            if name in allowed:
                return name
    if not local_enabled:
        return ""
    return sorted(allowed)[0]


async def filter_catalog(items: list[dict], user: dict) -> list[dict]:
    allowed = await allowed_for(user)
    if allowed is None:
        return items
    return [m for m in items if m.get("key") in allowed or (m.get("alias") or "") in allowed]
