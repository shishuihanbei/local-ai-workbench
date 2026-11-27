"""可达本地平台模型：把已启动的 OpenAI 兼容服务暴露到前端模型下拉。

这里不启动模型，也不安装引擎；只探测部署页里已配置并健康的平台，
把它的 `/v1/models` 结果转成前端可选择的模型条目。请求路由命中后，
仍由聊天链路直接调用该平台的 `/v1/chat/completions`。
"""
from __future__ import annotations

import re
import time
from typing import Any

from ..config import load_config
from .. import ollama_tags
from . import platform_store, platforms

_CACHE: dict[str, Any] = {"at": 0.0, "items": []}
_TTL_SECONDS = 8.0


def is_embedding_model(model_id: str) -> bool:
    """判断平台模型是不是向量/重排模型；这类模型不能当聊天模型用。

    平台只给 /v1/models 的 id，没有能力字段，只能按常见命名识别：
    text-embedding-*、nomic-embed-*、mxbai-embed-*、bge-*、gte-*、e5-*、
    all-minilm、rerank、cross-encoder、colbert 等。
    """
    s = re.sub(r"[^a-z0-9]+", "-", str(model_id or "").lower()).strip("-")
    if not s:
        return False
    if any(k in s for k in ("embed", "bge", "minilm", "rerank", "colbert", "cross-encoder")):
        return True
    return bool(re.search(r"(^|-)(e5|gte)(-|$)", s))


def is_vision_model(model_id: str) -> bool:
    """按常见命名识别能直接看图片的平台模型。

    平台 /v1/models 不返回 modalities，只能按家族名判断：
    Qwen-VL / Qwen2.5-VL / Qwen3-VL、LLaVA、MiniCPM-V、InternVL、Pixtral、
    Moondream、Gemma 3（4B 以上）、Llama 3.2 Vision、Mistral Small 3.1、
    Phi-4 Multimodal、SmolVLM、Idefics、CogVLM、Ovis、Qwen-Omni 等。
    识别偏保守：宁可让用户手动确认，也不把纯文本模型误标成视觉。
    """
    s = re.sub(r"[^a-z0-9.]+", "-", str(model_id or "").lower()).strip("-")
    if not s:
        return False
    if is_embedding_model(s):
        return False
    if "qwen" in s and ("vl" in s or "omni" in s):
        return True
    if any(k in s for k in (
            "llava", "minicpm-v", "internvl", "pixtral", "moondream",
            "smolvlm", "idefics", "cogvlm", "ovis", "llama-3.2-vision",
            "llama3.2-vision", "mistral-small-3.1", "mistral-small3.1",
            "phi-4-multimodal", "phi-3.5-vision", "phi-3-vision",
            "granite-3.2-vision", "granite3.2-vision", "video-llava",
            "llava-next-video", "videollama", "minicpm-o")):
        return True
    if "gemma-3" in s or "gemma3" in s:
        return not bool(re.search(r"(^|-)(1b|270m)(-|$)", s))
    return bool(re.search(r"(^|-)(vl|vision)(-|$)", s))


def invalidate() -> None:
    """平台地址、部署状态或模型列表变化后清空缓存。"""
    _CACHE["at"] = 0.0
    _CACHE["items"] = []


def _v1_base(root: str) -> str:
    base = str(root or "").rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1") else f"{base}/v1"


async def reachable(cfg: dict[str, Any] | None = None, ttl: float = _TTL_SECONDS,
                    llama_status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """返回当前健康平台上可直接调用的模型条目。"""
    now = time.time()
    if _CACHE["items"] and now - _CACHE["at"] <= ttl:
        return list(_CACHE["items"])

    cfg = cfg or load_config()
    selected = platforms.normalize_selected(cfg.get("deploy_platforms"))
    status_items = await platforms.status(cfg, selected, llama_status=llama_status, probe_all=False)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in status_items:
        if item.get("key") == "llama.cpp" or not item.get("healthy"):
            continue
        base = _v1_base(item.get("base_url") or "")
        if not base:
            continue
        platform_name = str(item.get("name") or item.get("key") or "外部平台")
        model_ids = list(item.get("models") or [])
        # /api/tags 偶尔会落后磁盘：直接读 Ollama manifests 兜底，
        # 刚 pull 完不用重启服务就能被前端看到。
        if item.get("key") == "ollama":
            for tag in ollama_tags.local_tags(platform_store.models_dir(cfg, "ollama")):
                if tag not in model_ids:
                    model_ids.append(tag)
        for model_id in model_ids:
            mid = str(model_id or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            embedding = is_embedding_model(mid)
            vision = (not embedding) and is_vision_model(mid)
            if embedding:
                category, label, kind = "embedding", "向量 / 检索", "embedding"
            elif vision:
                category, label, kind = "vision", "多模态 / 视觉", "vision"
            else:
                category, label, kind = "text", "文字 / 对话", "chat"
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
                "category": category,
                "category_label": label,
                "model_kind": kind,
                "vision": vision,
                "modalities": ["text", "image"] if vision else ["text"],
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
