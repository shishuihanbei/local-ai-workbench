"""每用户 Token 配额：按本地自然日 / 自然月统计 requests 表。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import fetch_one


def _day_start() -> float:
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _month_start() -> float:
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


async def usage(user_id: int) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT daily_token_limit,monthly_token_limit FROM users WHERE id=?", (user_id,)) or {}
    used = await fetch_one(
        "SELECT "
        "COALESCE(SUM(CASE WHEN created_at>=? THEN total_tokens ELSE 0 END),0) today,"
        "COALESCE(SUM(CASE WHEN created_at>=? THEN total_tokens ELSE 0 END),0) month "
        "FROM requests WHERE user_id=?", (_day_start(), _month_start(), user_id)) or {}
    return {
        "daily_limit": int(row.get("daily_token_limit") or 0),
        "monthly_limit": int(row.get("monthly_token_limit") or 0),
        "today": int(used.get("today") or 0),
        "month": int(used.get("month") or 0),
    }


async def check(user: dict[str, Any]) -> tuple[bool, str]:
    """管理员不受配额限制；普通用户超出返回 (False, 原因)。"""
    if not user or user.get("role") == "admin":
        return True, ""
    u = await usage(int(user["id"]))
    if u["daily_limit"] and u["today"] >= u["daily_limit"]:
        return False, f"今日 Token 配额已用完（{u['today']:,}/{u['daily_limit']:,}）"
    if u["monthly_limit"] and u["month"] >= u["monthly_limit"]:
        return False, f"本月 Token 配额已用完（{u['month']:,}/{u['monthly_limit']:,}）"
    return True, ""
