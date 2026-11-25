"""后台附件重新解析任务：串行执行，控制台轮询进度。"""
from __future__ import annotations

import asyncio
import time
import uuid

from ..db import fetch_one
from . import attachments

_JOBS: dict[str, dict] = {}
_ACTIVE = ""


class JobBusy(RuntimeError):
    pass


def public(job: dict) -> dict:
    current_elapsed = (job.get("finished_at") or time.time()) - job["started_at"]
    return {
        "id": job["id"],
        "status": job["status"],
        "total": job["total"],
        "done": job["done"],
        "ok": job["ok"],
        "failed": job["failed"],
        "empty": job["empty"],
        "current": job.get("current") or "",
        "elapsed_ms": int(current_elapsed * 1000),
        "results": job["results"][-120:],
        "error": job.get("error") or "",
    }


def start(ids: list[int]) -> dict:
    global _ACTIVE
    if _ACTIVE:
        active = _JOBS.get(_ACTIVE) or {}
        raise JobBusy(f"已有一个解析任务在运行（{active.get('done', 0)}/{active.get('total', 0)}）")
    clean: list[int] = []
    for value in ids:
        try:
            n = int(value)
        except Exception:
            continue
        if n > 0 and n not in clean:
            clean.append(n)
    if not clean:
        raise ValueError("没有需要重新解析的附件")
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id, "status": "running", "total": len(clean), "done": 0,
        "ok": 0, "failed": 0, "empty": 0, "current": "", "error": "",
        "results": [], "started_at": time.time(), "finished_at": 0,
    }
    _JOBS[job_id] = job
    _ACTIVE = job_id
    if len(_JOBS) > 40:
        for key in [k for k, v in _JOBS.items() if v["status"] != "running"][:-20]:
            _JOBS.pop(key, None)
    job["task"] = asyncio.create_task(_worker(job_id, clean))
    return public(job)


async def _worker(job_id: str, ids: list[int]) -> None:
    global _ACTIVE
    job = _JOBS[job_id]
    try:
        for n, file_id in enumerate(ids, 1):
            row = await fetch_one("SELECT * FROM uploads WHERE id=?", (file_id,))
            if not row:
                item = {"id": file_id, "ok": False, "chars": 0, "ms": 0,
                        "error": "附件记录不存在"}
            else:
                job["current"] = str(row.get("name") or f"#{file_id}")
                item = await attachments.reparse(row)
            if item.get("ok"):
                job["ok"] += 1
            else:
                job["failed"] += 1
            if not item.get("chars"):
                job["empty"] += 1
            job["done"] = n
            job["results"].append(item)
            await asyncio.sleep(0)
    except Exception as e:
        job["error"] = str(e)[:200]
    finally:
        job["current"] = ""
        job["status"] = "done"
        job["finished_at"] = time.time()
        job.pop("task", None)
        _ACTIVE = ""


def get(job_id: str) -> dict | None:
    job = _JOBS.get(job_id)
    return public(job) if job else None
