"""生成文档保留策略：计算到期时间、定时清理物理文件、为前端补充剩余时间。"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from ..config import EXPORT_DIR, load_config
from ..db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)

DEFAULT_DAYS = 30
MIN_DAYS = 1
MAX_DAYS = 365
WARN_DAYS = 3
CHECK_SECONDS = 3600
PERIOD = 86400

_stop = asyncio.Event()
_worker: asyncio.Task | None = None
last_cleanup_at = 0.0
last_result: dict[str, int] = {}


def clamp_days(value: object, fallback: int = DEFAULT_DAYS) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = fallback
    return max(MIN_DAYS, min(MAX_DAYS, days))


def retention_days(cfg: dict | None = None) -> int:
    cfg = cfg or load_config()
    return clamp_days(cfg.get("generated_file_retention_days"))


def expires_at(created_at: float, cfg: dict | None = None) -> float:
    return float(created_at) + retention_days(cfg) * PERIOD


def _local_text(ts: float, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts)).strftime(fmt)
    except (ValueError, OSError, OverflowError):
        return ""


def expiry_fields(expires_at_value: float | None, deleted_at: float = 0,
                  now: float | None = None) -> dict:
    """返回统一的到期字段；旧数据没有到期时间时保持兼容。"""
    now = time.time() if now is None else float(now)
    exp = float(expires_at_value or 0)
    cleaned = float(deleted_at or 0) > 0
    expired = cleaned or (exp > 0 and exp <= now)
    seconds_left = max(0, int(exp - now)) if exp > 0 and not cleaned else 0
    days_left = (seconds_left + PERIOD - 1) // PERIOD if seconds_left else 0
    soon = bool(exp > 0 and not expired and seconds_left <= WARN_DAYS * PERIOD)
    return {
        "expires_at": round(exp, 3) if exp else 0,
        "expires_text": _local_text(exp),
        "expires_date": _local_text(exp, "%Y-%m-%d"),
        "deleted_at": round(float(deleted_at or 0), 3),
        "deleted_text": _local_text(float(deleted_at or 0)),
        "days_left": days_left,
        "hours_left": max(0, (seconds_left + 3599) // 3600) if seconds_left else 0,
        "expiring_soon": soon,
        "expired": expired,
        "cleaned": cleaned,
        "warn_days": WARN_DAYS,
    }


def decorate_file(file: dict, now: float | None = None) -> dict:
    file.update(expiry_fields(file.get("expires_at"), file.get("deleted_at") or 0, now))
    return file


def decorate_files(files: list[dict], now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    for item in files:
        decorate_file(item, now)
    return files


async def cleanup_once() -> dict[str, int]:
    """删除已过期的物理文件并保留数据库行，历史消息可显示“已自动清理”。"""
    global last_cleanup_at, last_result
    now = time.time()
    rows = await fetch_all(
        "SELECT id,stored_name,size FROM generated_files "
        "WHERE deleted_at=0 AND expires_at>0 AND expires_at<=?", (now,))
    result = {"checked": len(rows), "removed": 0, "freed_bytes": 0,
              "missing": 0, "failed": 0}
    for row in rows:
        name = Path(str(row.get("stored_name") or "")).name
        path = EXPORT_DIR / name if name else None
        if not name or not path:
            result["failed"] += 1
            continue
        try:
            if path.exists():
                path.unlink()
                result["removed"] += 1
                result["freed_bytes"] += int(row.get("size") or 0)
            else:
                result["missing"] += 1
        except OSError as exc:
            result["failed"] += 1
            log.warning("清理生成文档失败 id=%s: %s", row.get("id"), exc)
            continue
        await execute("UPDATE generated_files SET deleted_at=? WHERE id=?", (now, row["id"]))
    last_cleanup_at = now
    last_result = result
    if rows:
        log.info("生成文档自动清理：到期 %s，删除 %s，释放 %s 字节，失败 %s",
                 len(rows), result["removed"], result["freed_bytes"], result["failed"])
    return result


async def apply_days(days: int) -> dict:
    """按新周期重算所有未清理文件的到期时间，然后立刻清理已经到期的文件。"""
    days = clamp_days(days)
    await execute(
        "UPDATE generated_files SET expires_at=created_at+? WHERE deleted_at=0",
        (days * PERIOD,))
    cleanup = await cleanup_once()
    return {"days": days, **cleanup}


async def stats(days: int | None = None) -> dict:
    now = time.time()
    days = retention_days() if days is None else clamp_days(days)
    total = await fetch_one("SELECT COUNT(*) c FROM generated_files") or {}
    retained = await fetch_one(
        "SELECT COUNT(*) c, COALESCE(SUM(size),0) s FROM generated_files "
        "WHERE deleted_at=0 AND expires_at>?", (now,)) or {}
    pending = await fetch_one(
        "SELECT COUNT(*) c, COALESCE(SUM(size),0) s FROM generated_files "
        "WHERE deleted_at=0 AND expires_at>0 AND expires_at<=?", (now,)) or {}
    soon = await fetch_one(
        "SELECT COUNT(*) c FROM generated_files "
        "WHERE deleted_at=0 AND expires_at>? AND expires_at<=?",
        (now, now + WARN_DAYS * PERIOD)) or {}
    cleaned = await fetch_one(
        "SELECT COUNT(*) c FROM generated_files WHERE deleted_at>0") or {}
    return {
        "days": days,
        "warn_days": WARN_DAYS,
        "total_files": int(total.get("c") or 0),
        "retained_files": int(retained.get("c") or 0),
        "retained_bytes": int(retained.get("s") or 0),
        "expiring_soon": int(soon.get("c") or 0),
        "pending_cleanup": int(pending.get("c") or 0),
        "pending_bytes": int(pending.get("s") or 0),
        "cleaned_files": int(cleaned.get("c") or 0),
        "last_cleanup_at": round(last_cleanup_at, 3),
        "last_cleanup_text": _local_text(last_cleanup_at, "%Y-%m-%d %H:%M:%S"),
        "last_result": dict(last_result),
        "check_seconds": CHECK_SECONDS,
    }


async def _loop() -> None:
    # 启动后先清理一次，之后每小时检查；到期判断使用本机时间。
    while not _stop.is_set():
        try:
            await cleanup_once()
        except Exception:
            log.exception("生成文档自动清理失败")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=CHECK_SECONDS)
        except asyncio.TimeoutError:
            pass


async def start() -> None:
    global _worker
    _stop.clear()
    if _worker and not _worker.done():
        return
    _worker = asyncio.create_task(_loop())
    log.info("生成文档保留策略已启动：默认保留 %s 天，每小时清理", retention_days())


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
