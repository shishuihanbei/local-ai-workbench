"""模型页的优缺点、Qwen3.6 收录与本机推荐口径。"""
from __future__ import annotations

from backend import model_guides, ollama_tags
from backend.db import OLLAMA_MODEL_CATALOG
from backend.services import hardware

PROF = {
    "cpu": "Intel(R) Core(TM) i7-3770 CPU @ 3.40GHz", "cores": 8,
    "ram_total_gb": 32.0, "ram_free_gb": 20.4,
    "gpus": [{"name": "GeForce GTX 650", "vram_mb": 1024}],
}


def test_qwen36_catalog_entries_have_ollama_tags():
    keys = {m["key"] for m in OLLAMA_MODEL_CATALOG}
    assert {"ollama-qwen36-27b", "ollama-qwen36-35b"} <= keys
    assert ollama_tags.tag_for("ollama-qwen36-27b") == "qwen3.6:27b"
    assert ollama_tags.tag_for("ollama-qwen36-35b") == "qwen3.6:35b-a3b"


def test_every_ollama_catalog_entry_has_pros_and_cons():
    for m in OLLAMA_MODEL_CATALOG:
        guide = model_guides.guide_for(
            m["key"], m.get("category", "text"), m["note"], m["engine"],
            int(m["total_bytes"]), m.get("engine", "Ollama"),
        )
        assert guide["pros"], m["key"]
        assert guide["cons"], m["key"]


def test_qwen36_27b_guide_mentions_vision_and_cpu_cost():
    guide = model_guides.guide_for(
        "ollama-qwen36-27b", "text", "Ollama tag · 27B Dense · 18GB", "Ollama",
        18 * 1024 ** 3, "Ollama",
    )
    joined = " ".join(guide["pros"] + guide["cons"])
    assert "视觉" in joined
    assert "CPU" in joined


def test_advise_recommends_small_models_and_warns_on_27b():
    small = hardware.advise(int(5.0 * 1024 ** 3), PROF)
    assert small["level"] == "good"
    assert small["speed_tps"] >= 4

    mid = hardware.advise(int(9.0 * 1024 ** 3), PROF)
    assert mid["level"] == "ok"

    big = hardware.advise(int(18.0 * 1024 ** 3), PROF)
    assert big["level"] == "warn"
    assert big["speed_tps"] < 2
    assert "纯 CPU" in big["text"]

    huge = hardware.advise(int(32.0 * 1024 ** 3), PROF)
    assert huge["level"] == "warn"
