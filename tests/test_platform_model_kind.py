"""平台模型要区分聊天模型和向量模型，向量模型不能进对话下拉。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from backend.services import platform_models

ROOT = Path(__file__).resolve().parents[1]


def test_embedding_model_names_are_recognized():
    for name in (
        "text-embedding-nomic-embed-text-v1.5",
        "nomic-embed-text:latest",
        "mxbai-embed-large",
        "bge-m3",
        "gte-large",
        "e5-large-v2",
        "all-minilm",
        "jina-embeddings-v3",
        "BAAI/bge-reranker-v2-m3",
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ):
        assert platform_models.is_embedding_model(name), name
    for name in (
        "deepseek-r1:1.5b",
        "qwen2.5:7b",
        "qwen3-8b",
        "deepseek-r1-0528-qwen3-8b",
        "llama3.2:3b",
        "text-generation-webui",
    ):
        assert not platform_models.is_embedding_model(name), name


def test_platform_models_are_classified_by_kind(monkeypatch):
    cfg = {"deploy_platforms": ["lmstudio"], "platform_endpoints": {}}

    async def status(*args, **kwargs):
        return [{
            "key": "lmstudio", "name": "LM Studio", "healthy": True,
            "base_url": "http://127.0.0.1:1234",
            "models": ["text-embedding-nomic-embed-text-v1.5", "qwen2.5-7b-instruct",
                       "qwen2.5vl:3b"],
            "homepage": "https://lmstudio.ai/", "multimodal": "部分",
        }]

    monkeypatch.setattr(platform_models.platforms, "status", status)
    platform_models.invalidate()
    items = asyncio.run(platform_models.reachable(cfg, ttl=0.1))
    by_key = {m["key"]: m for m in items}
    assert by_key["text-embedding-nomic-embed-text-v1.5"]["category"] == "embedding"
    assert by_key["text-embedding-nomic-embed-text-v1.5"]["model_kind"] == "embedding"
    assert by_key["qwen2.5-7b-instruct"]["category"] == "text"
    assert by_key["qwen2.5-7b-instruct"]["model_kind"] == "chat"
    assert by_key["qwen2.5vl:3b"]["category"] == "vision"
    assert by_key["qwen2.5vl:3b"]["model_kind"] == "vision"
    assert by_key["qwen2.5vl:3b"]["vision"] is True


def test_frontend_chat_dropdown_takes_text_code_and_vision():
    src = (ROOT / "frontend/models.js").read_text(encoding="utf-8")
    assert '["text", "code", "vision"].includes(m.category || "text")' in src
