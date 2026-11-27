"""知识库向量重排：用已启动平台上的 embedding 模型给关键词候选重新排序。

不建整库向量索引，只对“关键词已经命中的候选”做一次语义相似度重排：
- 现有知识库不用重建，选完模型立刻生效；
- 模型没启动或接口失败时自动退回原来的关键词排序，不影响对话；
- 向量模型仍只出现在知识库设置里，不进聊天模型下拉。
"""
from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from ..config import load_config
from . import platform_models, platforms

log = logging.getLogger("workbench.kb.embed")
MAX_CANDIDATES = 30
MAX_CHARS = 1200
EMBED_TIMEOUT = 30.0


def _model_id(platform_key: str, model: str) -> str:
    return f"{platform_key}::{model}"


def current(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    platform = str(cfg.get("kb_embedding_platform") or "")
    model = str(cfg.get("kb_embedding_model") or "")
    return {
        "vector_enabled": bool(cfg.get("kb_vector_rerank")),
        "embedding_platform": platform,
        "embedding_model": model,
        "id": _model_id(platform, model) if platform and model else "",
    }


async def available(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """当前健康平台上可用的向量模型。只收 embedding，不收聊天模型。"""
    cfg = cfg or load_config()
    items = await platform_models.reachable(cfg)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if item.get("category") != "embedding":
            continue
        platform_key = str(item.get("platform_key") or item.get("engine") or "")
        model = str(item.get("key") or "").strip()
        if not platform_key or not model:
            continue
        mid = _model_id(platform_key, model)
        if mid in seen:
            continue
        seen.add(mid)
        out.append({
            "id": mid,
            "platform": platform_key,
            "platform_name": str(item.get("source_platform") or platform_key),
            "model": model,
            "label": f"{model} · {item.get('source_platform') or platform_key}",
        })
    return out


def _v1_base(root: str) -> str:
    base = str(root or "").rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1") else f"{base}/v1"


async def _resolve(cfg: dict[str, Any]) -> dict[str, Any] | None:
    state = current(cfg)
    if not state["vector_enabled"] or not state["embedding_platform"] or not state["embedding_model"]:
        return None
    base = _v1_base(platforms.endpoints(cfg).get(state["embedding_platform"], ""))
    if not base:
        return None
    return {"platform": state["embedding_platform"], "model": state["embedding_model"], "base": base}


def _vectors(payload: Any, expected: int) -> list[list[float]]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != expected:
        raise ValueError("向量接口返回条数不对")
    rows = sorted(rows, key=lambda x: int((x or {}).get("index") or 0))
    out: list[list[float]] = []
    for row in rows:
        vec = (row or {}).get("embedding") if isinstance(row, dict) else None
        if not isinstance(vec, (list, tuple)) or not vec:
            raise ValueError("向量接口没有返回 embedding")
        out.append([float(x) for x in vec])
    return out


async def embed_texts(texts: list[str], cfg: dict[str, Any] | None = None) -> list[list[float]]:
    """调用 OpenAI 兼容 /v1/embeddings；批量失败时逐个重试。"""
    if not texts:
        return []
    cfg = cfg or load_config()
    target = await _resolve(cfg)
    if not target:
        raise RuntimeError("没有可用的向量模型")
    url = target["base"] + "/embeddings"
    body = {"model": target["model"], "input": [str(t)[:MAX_CHARS] for t in texts]}
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
        try:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return _vectors(resp.json(), len(texts))
        except Exception as batch_error:
            if len(texts) == 1:
                raise batch_error
            out: list[list[float]] = []
            for text in texts:
                resp = await client.post(url, json={"model": target["model"],
                                                    "input": str(text)[:MAX_CHARS]})
                resp.raise_for_status()
                out.extend(_vectors(resp.json(), 1))
            return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


async def rerank(query: str, rows: list[dict[str, Any]],
                 cfg: dict[str, Any] | None = None) -> dict[int, float]:
    """返回 doc_id -> 最高余弦相似度；失败返回空字典，调用方继续用关键词排序。"""
    if not query or not rows:
        return {}
    cfg = cfg or load_config()
    if not bool(cfg.get("kb_vector_rerank")):
        return {}
    picked = rows[:MAX_CANDIDATES]
    texts = []
    for row in picked:
        title = str(row.get("title") or "")
        content = str(row.get("content") or "")
        texts.append((title + "\n" + content).strip()[:MAX_CHARS])
    try:
        vectors = await embed_texts([query, *texts], cfg)
    except Exception as exc:
        log.warning("知识库向量重排失败，退回关键词排序：%s", exc)
        return {}
    if len(vectors) != len(texts) + 1:
        return {}
    qv, dvs = vectors[0], vectors[1:]
    sims: dict[int, float] = {}
    for row, vec in zip(picked, dvs):
        try:
            doc_id = int(row.get("doc_id"))
        except Exception:
            continue
        sims[doc_id] = max(sims.get(doc_id, 0.0), cosine(qv, vec))
    return sims
