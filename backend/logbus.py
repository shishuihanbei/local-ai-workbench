"""一队列：请求/span 异步批量落库。

请求线程只负责 put 一个 dict，worker 在后台按批写入 requests / spans，
这样以后加影子流量、RAG 检索、工具调用都不会拖慢首字。

想换成 Redis/ARQ 时，只需把 QUEUE.put 换成 redis 入队、worker 独立进程消费，
事件结构保持不变。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .db import connect

log = logging.getLogger("workbench.logbus")

QUEUE: asyncio.Queue = asyncio.Queue(maxsize=20000)
TASK: asyncio.Task | None = None
DROP_COUNT = 0


async def put(event: dict) -> bool:
    """非阻塞入队；队列满时丢弃并计数，绝不阻塞请求。"""
    global DROP_COUNT
    try:
        QUEUE.put_nowait(event)
        return True
    except asyncio.QueueFull:
        DROP_COUNT += 1
        if DROP_COUNT % 100 == 1:
            log.warning("日志队列已满，累计丢弃 %s 条", DROP_COUNT)
        return False


def _request_row(e: dict) -> tuple:
    r = e.get("request", {})
    return (
        r.get("trace_id", ""), r.get("user_id"), r.get("conversation_id"),
        r.get("route_id"), r.get("provider"), r.get("provider_id"), r.get("model"),
        1 if r.get("stream", True) else 0, r.get("status", "ok"), r.get("error"),
        r.get("prompt_version"), r.get("prompt_hash"), r.get("prompt_rendered"),
        r.get("params_json"), r.get("decision_json"),
        int(r.get("prompt_tokens") or 0), int(r.get("completion_tokens") or 0),
        int(r.get("total_tokens") or 0), 1 if r.get("tokens_estimated") else 0,
        float(r.get("cost") or 0), float(r.get("price_in") or 0), float(r.get("price_out") or 0),
        int(r.get("ttft_ms") or 0), int(r.get("total_ms") or 0), int(r.get("queue_ms") or 0),
        int(r.get("retries") or 0), 1 if r.get("cache_hit") else 0, r.get("cache_id"),
        r.get("experiment_id"), int(r.get("bucket") or 0), r.get("shadow_of"),
        r.get("created_at") or time.time(),
    )


INSERT_SQL = (
    "INSERT INTO requests(trace_id,user_id,conversation_id,route_id,provider,provider_id,model,"
    "stream,status,error,prompt_version,prompt_hash,prompt_rendered,params_json,decision_json,"
    "prompt_tokens,completion_tokens,total_tokens,tokens_estimated,cost,price_in,price_out,"
    "ttft_ms,total_ms,queue_ms,retries,cache_hit,cache_id,experiment_id,bucket,shadow_of,created_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


async def _flush_batch(batch: list[dict]) -> None:
    db = await connect()
    try:
        for e in batch:
            cur = await db.execute(INSERT_SQL, _request_row(e))
            rid = cur.lastrowid
            tx = e.get("request", {}).get("trace_id", "")
            spans = e.get("spans") or []
            for s in spans:
                await db.execute(
                    "INSERT INTO spans(request_id,trace_id,kind,name,start_ms,dur_ms,attrs_json,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (rid, tx, s.get("kind", "llm"), s.get("name", ""),
                     int(s.get("start_ms") or 0), int(s.get("dur_ms") or 0),
                     json.dumps(s.get("attrs") or {}, ensure_ascii=False), time.time()))
        await db.commit()
    except Exception:
        log.exception("批量写入失败，丢弃 %s 条", len(batch))
    finally:
        await db.close()


async def worker() -> None:
    log.info("日志队列 worker 已启动")
    while True:
        try:
            first = await QUEUE.get()
            batch = [first]
            deadline = time.monotonic() + 1.0
            while len(batch) < 200 and time.monotonic() < deadline:
                try:
                    batch.append(QUEUE.get_nowait())
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.02)
            await _flush_batch(batch)
            for _ in batch:
                QUEUE.task_done()
        except asyncio.CancelledError:
            # 退出前清空队列
            while not QUEUE.empty():
                batch = []
                while not QUEUE.empty() and len(batch) < 200:
                    batch.append(QUEUE.get_nowait())
                if batch:
                    await _flush_batch(batch)
            raise
        except Exception:
            log.exception("worker 异常，1 秒后继续")
            await asyncio.sleep(1)


def start() -> None:
    global TASK
    if TASK is None or TASK.done():
        TASK = asyncio.create_task(worker())


async def stop() -> None:
    global TASK
    if TASK:
        TASK.cancel()
        try:
            await TASK
        except asyncio.CancelledError:
            pass
        TASK = None
