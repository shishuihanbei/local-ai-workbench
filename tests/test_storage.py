from pathlib import Path

import pytest

from backend import config as cfgmod
from backend.services import storage


def test_defaults_live_under_program_root():
    root = cfgmod.BASE_DIR
    assert cfgmod.default_models_dir() == root / "models"
    assert cfgmod.default_platforms_dir() == root / "platforms"
    assert cfgmod.default_llama_dir() == root / "platforms" / "llama.cpp"


def test_set_paths_creates_dirs_and_moves_llama_under_platforms(tmp_path):
    cfg = cfgmod.load_config()
    keys = ("models_dir", "platforms_dir", "llama_dir", "llama_bin")
    old = {k: cfg.get(k) for k in keys}
    try:
        models = tmp_path / "my-models"
        platforms = tmp_path / "my-platforms"
        result = storage.set_paths(str(models), str(platforms))
        assert result["ok"] is True
        assert models.is_dir() and platforms.is_dir()
        cfg = cfgmod.load_config()
        assert cfg["models_dir"] == str(models)
        assert cfg["platforms_dir"] == str(platforms)
        assert cfg["llama_dir"] == str(platforms / "llama.cpp")
        assert cfg["llama_bin"] == ""

        with pytest.raises(ValueError):
            storage.set_paths("relative/models", None)
        a_file = tmp_path / "a-file"
        a_file.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError):
            storage.set_paths(str(a_file), None)
    finally:
        cfg = cfgmod.load_config()
        for key, value in old.items():
            if value is not None:
                cfg[key] = value
        cfgmod.save_config(cfg)


def test_status_reports_existing_dirs(tmp_path):
    cfg = cfgmod.load_config()
    keys = ("models_dir", "platforms_dir", "llama_dir", "llama_bin")
    old = {k: cfg.get(k) for k in keys}
    try:
        storage.set_paths(str(tmp_path / "models"), str(tmp_path / "platforms"))
        st = storage.status()
        assert st["models_dir"] == str(tmp_path / "models")
        assert st["models_dir_exists"] is True
        assert st["platforms_dir"] == str(tmp_path / "platforms")
        assert st["platforms_dir_exists"] is True
        assert st["llama_dir"] == str(tmp_path / "platforms" / "llama.cpp")
        assert st["defaults"]["models_dir"] == str(cfgmod.default_models_dir())
    finally:
        cfg = cfgmod.load_config()
        for key, value in old.items():
            if value is not None:
                cfg[key] = value
        cfgmod.save_config(cfg)
