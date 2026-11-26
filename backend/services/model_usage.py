"""记录“本机 llama.cpp 正在生成”的会话，避免切换模型时把别人的回答掐断。

llama.cpp 一次只能加载一个权重，换模型必须重启进程；重启会中断所有正在
生成的 SSE 流。这里只做计数，不做调度：切换方自己决定是等待还是强制。

进程内单例，状态只在本进程有效；进程重启后自然清空。
"""
from __future__ import annotations

import time
from typing import Any

_STATE: dict[str, dict[str, Any]] = {}


def begin(model: str, user: str = "") -> None:
    """一次生成开始占用某个已加载模型。"""
    key = str(model or "").strip()
    if not key:
        return
    slot = _STATE.get(key)
    if not slot:
        slot = {"since": time.time(), "users": {}}
        _STATE[key] = slot
    who = str(user or "").strip() or "未命名用户"
    slot["users"][who] = int(slot["users"].get(who) or 0) + 1


def end(model: str, user: str = "") -> None:
    """生成结束（正常结束、出错、用户停止、断连）都要调用。"""
    key = str(model or "").strip()
    slot = _STATE.get(key)
    if not slot:
        return
    who = str(user or "").strip() or "未命名用户"
    left = int(slot["users"].get(who) or 0) - 1
    if left > 0:
        slot["users"][who] = left
    else:
        slot["users"].pop(who, None)
    if not slot["users"]:
        _STATE.pop(key, None)


def _entry(key: str, slot: dict[str, Any]) -> dict[str, Any]:
    users = {u: int(c or 0) for u, c in (slot.get("users") or {}).items()}
    return {
        "model": key,
        "count": sum(users.values()),
        "users": sorted(users),
        "users_count": users,
        "seconds": int(max(0, time.time() - float(slot.get("since") or time.time()))),
    }


def snapshot() -> list[dict[str, Any]]:
    """当前所有被占用的模型，按持续时长倒序。"""
    items = [_entry(k, v) for k, v in _STATE.items()]
    items = [i for i in items if i["count"] > 0]
    items.sort(key=lambda x: x["seconds"], reverse=True)
    for item in items:
        item.pop("users_count", None)
    return items


def busy(except_user: str = "") -> list[dict[str, Any]]:
    """排除某人自己发起的生成后，仍被别人占用的模型。"""
    skip = str(except_user or "").strip()
    out = []
    for key, slot in list(_STATE.items()):
        entry = _entry(key, slot)
        others = {u: c for u, c in entry.pop("users_count").items() if u != skip}
        if not others:
            continue
        entry["users"] = sorted(others)
        entry["count"] = sum(others.values())
        out.append(entry)
    out.sort(key=lambda x: x["seconds"], reverse=True)
    return out


def clear() -> None:
    """测试用。"""
    _STATE.clear()
