"""可达本地平台模型：把已启动的 OpenAI 兼容服务暴露到前端模型下拉。

这里不启动模型，也不安装引擎；只探测部署页里已配置并健康的平台，
把它的 `/v1/models` 结果转成前端可选择的模型条目。请求路由命中后，
仍由聊天链路直接调用该平台的 `/v1/chat/completions`。
"""
from __future__ import annotations

import time
from typing import Any

from ..config import load_config
from . import platforms

_CACHE: dict[str, Any] = {"at": 0.0, "items": []}
_TTL_SECONDS = 8.0


def invalidate() -> None:
    """平台地址、部署状态或模型列表变化后清空缓存。"""
    _CACHE["at"] = 0.0
    _CACHE["items"] = []


def _v1_base(root: str) -> str:
    base = str(root or "").rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1") else f"{base}/v1"


async def reachable(cfg: dict[str, Any] | None = None, ttl: float = _TTL_SECONDS) -> list[dict[str, Any]]:
    """返回当前健康平台上可直接调用的模型条目。"""
    now = time.time()
    if _CACHE["items"] and now - _CACHE["at"] <= ttl:
        return list(_CACHE["items"])

    cfg = cfg or load_config()
    selected = platforms.normalize_selected(cfg.get("deploy_platforms"))
    status_items = await platforms.status(cfg, selected, probe_all=False)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in status_items:
        if item.get("key") == "llama.cpp" or not item.get("healthy"):
            continue
        base = _v1_base(item.get("base_url") or "")
        if not base:
            continue
        platform_name = str(item.get("name") or item.get("key") or "外部平台")
        for model_id in item.get("models") or []:
            mid = str(model_id or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append({
                "key": mid,
                "alias": "",
                "label": mid,
                "family": platform_name,
                "note": f"来自本地部署平台 {platform_name} 的 OpenAI 兼容服务",
                "filename": "",
                "total_bytes": 0,
                "repo": "",
                "fit": "unknown",
                "sort": 800,
                "category": "text",
                "category_label": "文字 / 对话",
                "engine": str(item.get("key") or ""),
                "homepage": item.get("homepage") or "",
                "installable": False,
                "engine_repo": "",
                "engine_ready": True,
                "engine_recommend": platform_name,
                "engine_recommend_key": str(item.get("key") or ""),
                "engine_package": "",
                "engine_gpu": bool(item.get("multimodal")),
                "engine_text": "平台服务已启动，模型可直接在前端切换",
                "downloaded": True,
                "partial": False,
                "bytes": 0,
                "pct": 100,
                "available": True,
                "loaded": True,
                "owned_by": "platform",
                "source_platform": platform_name,
                "platform_key": str(item.get("key") or ""),
                "base_url": base,
                "advice": {"level": "good", "label": platform_name,
                           "text": "已在本地平台服务中检测到该模型"},
            })

    _CACHE["at"] = now
    _CACHE["items"] = out
    return list(out)
