"""知识库向量重排：不建全库索引，只给关键词候选做语义排序。"""
from __future__ import annotations

import asyncio
import json

import httpx


def _cfg() -> dict:
    return {
        "platforms_dir": "x", "models_dir": "x", "llama_dir": "x",
        "platform_endpoints": {"lmstudio": "http://127.0.0.1:1234"},
        "kb_vector_rerank": True,
        "kb_embedding_platform": "lmstudio",
        "kb_embedding_model": "text-embedding-nomic-embed-text-v1.5",
    }


def test_current_is_disabled_by_default():
    from backend.services import kb_embed

    assert kb_embed.current({})["vector_enabled"] is False
    assert kb_embed.current(_cfg())["id"] == (
        "lmstudio::text-embedding-nomic-embed-text-v1.5")


def test_available_only_returns_embedding_models(monkeypatch):
    from backend.services import kb_embed

    async def fake_reachable(cfg=None):
        return [
            {"key": "text-embedding-nomic-embed-text-v1.5", "category": "embedding",
             "platform_key": "lmstudio", "source_platform": "LM Studio"},
            {"key": "qwen2.5-7b-instruct", "category": "text",
             "platform_key": "lmstudio", "source_platform": "LM Studio"},
            {"key": "nomic-embed-text", "category": "embedding",
             "platform_key": "ollama", "source_platform": "Ollama"},
        ]

    monkeypatch.setattr(kb_embed.platform_models, "reachable", fake_reachable)
    out = asyncio.run(kb_embed.available(_cfg()))
    assert [x["model"] for x in out] == [
        "text-embedding-nomic-embed-text-v1.5", "nomic-embed-text"]
    assert out[0]["platform"] == "lmstudio"


def test_embed_texts_uses_openai_embeddings_shape(monkeypatch):
    from backend.services import kb_embed

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen.append(body)
        inputs = body["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        return httpx.Response(200, json={
            "data": [{"index": i, "embedding": [float(i + 1), 1.0]}
                     for i in range(len(inputs))],
        })

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    class Client(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(kb_embed.httpx, "AsyncClient", Client)
    monkeypatch.setattr(kb_embed.platforms, "endpoints",
                        lambda cfg: {"lmstudio": "http://127.0.0.1:1234"})
    vectors = asyncio.run(kb_embed.embed_texts(["退款流程", "多久到账"], _cfg()))
    assert len(vectors) == 2
    assert seen[0]["model"] == "text-embedding-nomic-embed-text-v1.5"
    assert isinstance(seen[0]["input"], list)


def test_rank_rows_prefers_semantic_candidate():
    from backend.services import kb

    rows = [
        {"doc_id": 1, "title": "退款流程说明", "content": "退款流程要几天",
         "score": -1.0, "scope": "global"},
        {"doc_id": 2, "title": "售后处理规范", "content": "收到货后如何申请退回款项",
         "score": -1.0, "scope": "global"},
    ]
    terms = ["退款", "流程", "几天"]
    result = kb._rank_rows(rows, terms, 2, {1: 0.2, 2: 0.9})
    assert [x["doc_id"] for x in result] == [2, 1]


def test_search_uses_vector_rerank(monkeypatch):
    from backend.services import kb, kb_embed

    rows = [
        {"doc_id": 1, "title": "退款流程说明", "content": "退款流程要几天",
         "snippet": "退款流程要几天", "score": -1.0, "scope": "global",
         "user_id": None, "username": "", "folder": "", "tags": ""},
        {"doc_id": 2, "title": "售后处理规范", "content": "收到货后如何申请退回款项",
         "snippet": "收到货后如何申请退回款项", "score": -1.0, "scope": "global",
         "user_id": None, "username": "", "folder": "", "tags": ""},
    ]

    async def fake_fetch_all(sql, params):
        return rows

    async def fake_rerank(query, picked, cfg):
        return {2: 0.9, 1: 0.2}

    monkeypatch.setattr(kb, "load_config", _cfg)
    monkeypatch.setattr(kb, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(kb_embed, "rerank", fake_rerank)
    out = asyncio.run(kb.search("退款流程要几天", top_k=2))
    assert [x["doc_id"] for x in out] == [2, 1]


def test_kb_pages_have_vector_selector():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    console_html = (root / "backend" / "console" / "index.html").read_text(encoding="utf-8")
    console_js = (root / "backend" / "console" / "panels" / "content.js").read_text(encoding="utf-8")
    user_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    user_js = (root / "frontend" / "settings.js").read_text(encoding="utf-8")
    assert 'id="kbVectorModel"' in console_html
    assert "/api/kb/embeddings" in console_js
    assert 'id="myKbVectorHint"' in user_html
    assert "向量语义重排" in user_js


def test_kb_settings_rejects_unavailable_embedding(client, admin_token, monkeypatch):
    from backend.services import kb_embed

    async def only_one(cfg=None):
        return [{"id": "lmstudio::nomic", "platform": "lmstudio",
                 "platform_name": "LM Studio", "model": "nomic",
                 "label": "nomic · LM Studio"}]

    monkeypatch.setattr(kb_embed, "available", only_one)
    h = {"Authorization": "Bearer " + admin_token}
    r = client.post("/api/kb/settings", params={
        "enabled": "true", "top_k": 3, "vector_enabled": "true",
        "embedding_platform": "ollama", "embedding_model": "nomic",
    }, headers=h)
    assert r.status_code == 400
    assert "不可用" in r.json()["detail"]
    r = client.post("/api/kb/settings", params={
        "enabled": "true", "top_k": 3, "vector_enabled": "true",
        "embedding_platform": "lmstudio", "embedding_model": "nomic",
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["vector_enabled"] is True
    assert r.json()["id"] == "lmstudio::nomic"
    r = client.get("/api/kb", headers=h)
    assert r.json()["vector_enabled"] is True
    assert r.json()["embedding_model"] == "nomic"
