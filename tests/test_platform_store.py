"""四个引擎的下载、安装、缓存全部落在工作台目录里，不往系统目录丢东西。"""
from __future__ import annotations

import os
from pathlib import Path

from backend.services import platform_store
from backend.config import DATA_DIR


def _cfg(tmp_path: Path) -> dict:
    return {
        "platforms_dir": str(tmp_path / "platforms"),
        "llama_dir": str(tmp_path / "platforms" / "llama.cpp"),
        "models_dir": str(tmp_path / "models"),
    }


def test_every_engine_lands_under_one_root(tmp_path):
    cfg = _cfg(tmp_path)
    root = platform_store.platforms_root(cfg)
    assert root == tmp_path / "platforms"
    for key in platform_store.MANAGED_ENGINES:
        target = platform_store.target(cfg, key)
        assert str(target).startswith(str(root)), key
    # llama.cpp 仍用老配置项，避免升级后找不到原来的安装
    assert platform_store.target(cfg, "llama.cpp") == Path(cfg["llama_dir"])
    assert platform_store.downloads(cfg) == root / ".downloads"
    assert platform_store.tmp_root(cfg) == root / ".tmp"


def test_engine_models_live_under_models_root(tmp_path):
    cfg = _cfg(tmp_path)
    models = Path(cfg["models_dir"])
    # 所有引擎的模型都在 models 根下，只是 Ollama / LM Studio 各占一层子目录
    assert platform_store.models_dir(cfg, "ollama") == models / "ollama"
    assert platform_store.models_dir(cfg, "lmstudio") == models / "lmstudio"
    assert platform_store.models_dir(cfg, "llama.cpp") == models
    assert platform_store.models_dir(cfg, "vllm") == models


def test_child_env_redirects_system_temp_and_caches(tmp_path):
    cfg = _cfg(tmp_path)
    home = tmp_path / "platforms" / "lmstudio" / "home"
    env = platform_store.child_env(cfg, {"LMS_NO_MODIFY_PATH": "1"}, home=home)
    root = str(platform_store.platforms_root(cfg))
    for name in ("TMP", "TEMP", "TMPDIR"):
        assert env[name].startswith(root), name
    assert env["PIP_CACHE_DIR"].startswith(str(DATA_DIR))
    assert env["HF_HOME"].startswith(str(DATA_DIR))
    assert env["XDG_CACHE_HOME"].startswith(str(DATA_DIR))
    assert env["HOME"] == str(home)
    assert env["LMS_NO_MODIFY_PATH"] == "1"
    if os.name == "nt":
        assert env["USERPROFILE"] == str(home)


def test_workbench_tmp_is_unique_and_inside(tmp_path):
    cfg = _cfg(tmp_path)
    a = platform_store.workbench_tmp(cfg, "llama-extract")
    b = platform_store.workbench_tmp(cfg, "llama-extract")
    assert a != b
    assert a.is_dir() and b.is_dir()
    assert platform_store.inside(a, cfg)
    assert not platform_store.inside(tmp_path / "somewhere-else", cfg)


def test_summary_lists_all_storage_without_scanning_models(tmp_path):
    cfg = _cfg(tmp_path)
    rows = platform_store.summary(cfg, with_sizes=False)
    keys = {r["key"] for r in rows}
    assert {"downloads", "tmp", "cache", "models", "models:ollama", "models:lmstudio", "data"} <= keys
    for key in platform_store.MANAGED_ENGINES:
        assert f"engine:{key}" in keys
    models_row = next(r for r in rows if r["key"] == "models")
    # 模型目录可能几百 GB，不给它算体积
    assert models_row["bytes"] == -1
    assert models_row["human"] == "—"
    assert all(isinstance(r["path"], str) and r["path"] for r in rows)


def test_human_units():
    assert platform_store.human(512) == "512 B"
    assert platform_store.human(2048) == "2 KB"
    assert platform_store.human(3 * 1024 ** 2) == "3 MB"
    assert platform_store.human(5 * 1024 ** 3) == "5.00 GB"
