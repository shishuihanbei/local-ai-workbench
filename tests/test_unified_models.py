"""模型统一放在 models 根下：Ollama / LM Studio 各占一层，老目录自动搬。"""
from __future__ import annotations

import json
from pathlib import Path


def _cfg(tmp_path: Path) -> dict:
    return {
        "platforms_dir": str(tmp_path / "platforms"),
        "models_dir": str(tmp_path / "models"),
        "llama_dir": str(tmp_path / "platforms" / "llama.cpp"),
        "ollama_dir": str(tmp_path / "platforms" / "ollama"),
    }


def test_ollama_models_migrate_into_models_root(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    old = tmp_path / "platforms" / "ollama" / "models"
    (old / "blobs").mkdir(parents=True)
    (old / "blobs" / "sha256-a").write_text("blob", encoding="utf-8")
    platform_deploy.ensure_model_layout(cfg)
    new = tmp_path / "models" / "ollama"
    assert (new / "blobs" / "sha256-a").read_text(encoding="utf-8") == "blob"
    assert not (old / "blobs" / "sha256-a").exists()


def test_lmstudio_models_migrate_and_config_points_to_models_root(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    home = tmp_path / "platforms" / "lmstudio" / "home"
    src = home / ".lmstudio" / "models" / "publisher" / "model"
    src.mkdir(parents=True)
    (src / "m.gguf").write_text("gguf", encoding="utf-8")
    platform_deploy.ensure_lmstudio_models(cfg)
    new = tmp_path / "models" / "lmstudio" / "publisher" / "model"
    assert (new / "m.gguf").read_text(encoding="utf-8") == "gguf"
    assert not (src / "m.gguf").exists()
    conf = json.loads((home / ".lmstudio" / "config.json").read_text(encoding="utf-8"))
    assert conf["modelsDirectory"] == str(tmp_path / "models" / "lmstudio")


def test_summary_lists_engine_model_dirs_under_models(tmp_path):
    from backend.services import platform_store

    rows = platform_store.summary(_cfg(tmp_path), with_sizes=False)
    by_key = {r["key"]: r for r in rows}
    assert by_key["models"]["path"] == str(tmp_path / "models")
    assert by_key["models:ollama"]["path"] == str(tmp_path / "models" / "ollama")
    assert by_key["models:lmstudio"]["path"] == str(tmp_path / "models" / "lmstudio")
