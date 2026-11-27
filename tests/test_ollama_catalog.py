"""Ollama 常用模型进内置清单：能在模型表里看到 tag 并直接拉取。"""
from __future__ import annotations

from backend import ollama_tags
from backend.db import OLLAMA_MODEL_CATALOG


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_ollama_catalog_entries_have_tags():
    assert OLLAMA_MODEL_CATALOG
    for m in OLLAMA_MODEL_CATALOG:
        assert m["engine"] == "Ollama"
        assert m["installable"] == 0
        assert m["category"] in ("text", "code")
        assert ollama_tags.tag_for(m["key"], m.get("alias", ""))
        assert m["homepage"].startswith("https://ollama.com/library/")


def test_models_api_lists_ollama_models_with_pull_tag(client, admin_token):
    r = client.get("/api/models", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    items = {m["key"]: m for m in body["items"]}
    for m in OLLAMA_MODEL_CATALOG:
        row = items.get(m["key"])
        assert row, f"{m['key']} 没进内置清单"
        assert row["engine"] == "Ollama"
        assert row["installable"] is False
        assert row["ollama_tag"] == ollama_tags.tag_for(m["key"], m.get("alias", ""))
        assert row["engine_recommend_key"] == "ollama"
        assert row["pros"] and row["cons"]
    qwen3 = items["ollama-qwen3-8b"]
    assert qwen3["category"] == "text"
    assert qwen3["ollama_tag"] == "qwen3:8b"
    assert qwen3["ollama_installed"] in (True, False)
    # 服务没跑时也应保留 tag，前端才能显示“未启动/需先装”
    assert qwen3["ollama_tag"]
    reco = body["recommendation"]
    assert reco["machine"]
    assert reco["picks"]
    assert reco["picks"][0]["reason"]
    for pick in reco["picks"]:
        assert items[pick["key"]]["pros"]


def test_pull_card_no_longer_claims_models_are_outside_catalog():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "backend/console/index.html").read_text(encoding="utf-8")
    assert "不在内置清单里" not in html
    assert "内置清单里标了 Ollama tag" in html
