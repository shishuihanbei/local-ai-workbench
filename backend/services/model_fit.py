"""模型适配：避免用 0.5B 这类玩具模型去接写报告、做 PPT 的真实任务。"""
from __future__ import annotations

import re
from typing import Any

_PARAM_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*b(?![a-z0-9])")
_TASK_RE = re.compile(
    r"(?i)写|撰写|生成|制作|做一份|整理|总结|分析|翻译|方案|报告|教案|课件|"
    r"ppt|幻灯片|演示文稿|word|excel|表格|pdf|代码|脚本|计划|大纲|论文|简历"
)
LIGHT_MAX_B = 1.5


def params_b(*texts: str) -> float | None:
    for text in texts:
        if not text:
            continue
        for m in _PARAM_RE.finditer(str(text)):
            try:
                value = float(m.group(1))
            except ValueError:
                continue
            if 0 < value <= 400:
                return value
    return None


def is_light(key: str, label: str = "") -> bool:
    value = params_b(key, label)
    if value is None:
        return False
    return value <= LIGHT_MAX_B


def needs_strong(message: str, fmt: str = "") -> bool:
    text = (message or "").strip()
    return bool(fmt) or len(text) >= 60 or bool(_TASK_RE.search(text))


async def stronger_model(cfg: dict[str, Any], current: str) -> dict[str, Any] | None:
    """按“默认模型 → 算力池 → 平台模型里参数最大的”顺序找可用强模型。"""
    from . import platform_models

    candidates: list[tuple[str, str]] = []
    default = str(cfg.get("model") or "").strip()
    if default and default != current and not is_light(default):
        candidates.append((default, "本机默认模型"))
    try:
        from ..db import fetch_all
        pools = await fetch_all("SELECT name FROM cluster_pools WHERE enabled=1 ORDER BY id")
        for row in pools or []:
            name = str(row["name"] or "").strip()
            if name and name != current:
                candidates.append((name, "可用算力池"))
    except Exception:
        pass
    # 默认模型和算力池都来自本地配置/数据库，必须先判断；
    # 只有二者都没有时才扫描平台模型，避免把网络探测放在聊天首包路径上。
    for key, source in candidates:
        if not is_light(key):
            return {"to": key, "reason": f"当前模型参数过小，已自动改用{source}"}
    try:
        platforms = await platform_models.reachable(cfg)
    except Exception:
        platforms = []
    scored: list[tuple[float, str, str]] = []
    for item in platforms:
        key = str(item.get("key") or "").strip()
        if not key or key == current or is_light(key, str(item.get("label") or "")):
            continue
        score = params_b(key, str(item.get("label") or "")) or 0
        scored.append((score, key, str(item.get("source_platform") or "本地平台")))
    for score, key, source in sorted(scored, reverse=True):
        candidates.append((key, f"{source} 模型"))
    for key, source in candidates:
        if not is_light(key):
            return {"to": key, "reason": f"当前模型参数过小，已自动改用{source}"}
    return None


async def maybe_escalate(body, cfg: dict[str, Any], fmt: str = "") -> dict[str, Any] | None:
    current = str(getattr(body, "model", "") or "").strip()
    if not current or not is_light(current):
        return None
    message = str(getattr(body, "message", "") or "")
    if not needs_strong(message, fmt):
        return None
    target = await stronger_model(cfg, current)
    if not target:
        return None
    return {"from": current, **target}
