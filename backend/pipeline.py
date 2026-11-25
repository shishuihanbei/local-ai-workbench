"""三钩子：Prompt 渲染前 / 调用前 / 调用后。

设计要点：
- 钩子以注册表形式挂载，新增缓存、灰度、影子流量只需再注册一个函数，不改主流程。
- 每个钩子拿到同一个 ctx（dict），可读写；返回 False 表示短路（例如缓存命中）。
- 钩子异常不影响主链路，只记入 ctx["hook_errors"]。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

HOOKS: dict[str, list] = {
    "before_render": [],
    "before_call": [],
    "after_call": [],
}


def register(stage: str, fn):
    if stage not in HOOKS:
        raise ValueError(f"未知钩子阶段 {stage}")
    HOOKS[stage].append(fn)
    return fn


async def run(stage: str, ctx: dict[str, Any]) -> bool:
    """依次执行钩子；返回 False 表示被短路（仅 before_* 阶段有意义）。"""
    ctx.setdefault("hook_errors", [])
    for fn in HOOKS[stage]:
        try:
            r = await fn(ctx)
            if r is False:
                return False
        except Exception as e:      # 观测钩子绝不能打断请求
            ctx["hook_errors"].append(f"{stage}:{getattr(fn, '__name__', 'hook')}:{e}")
    return True


def new_ctx(user: dict, body, cfg: dict) -> dict[str, Any]:
    now = time.time()
    ctx: dict[str, Any] = {
        "trace_id": uuid.uuid4().hex[:16],
        "user": user,
        "body": body,
        "cfg": cfg,
        "started_at": now,
        "t0": time.monotonic(),
        "decision": {"strategy": "local", "reason": "default"},
        "hooks": {},
    }
    return ctx


def prompt_hash(model: str, prompt: str, params: dict, scope: str = "default") -> str:
    raw = json.dumps([scope, model, prompt, params], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """粗略估算：中文约 1 字 1 token，英文约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)
