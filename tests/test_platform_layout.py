"""平台程序与模型的落位：Ollama 必须进 platforms/ollama，卡片要能说清目录。"""
from __future__ import annotations

from pathlib import Path

import pytest


def _fake_cfg(tmp_path: Path) -> dict:
    return {
        "platforms_dir": str(tmp_path / "platforms"),
        "ollama_dir": str(tmp_path / "platforms" / "ollama"),
        "ollama_models": "",
    }


def test_ollama_paths_default_under_platforms(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _fake_cfg(tmp_path))
    assert platform_deploy.ollama_dir().parts[-2:] == ("platforms", "ollama")
    assert platform_deploy.ollama_models_dir().parts[-3:] == ("platforms", "ollama", "models")


def test_ollama_dir_follows_platforms_dir(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = {"platforms_dir": str(tmp_path / "moved" / "platforms"), "ollama_dir": "", "ollama_models": ""}
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    assert platform_deploy.ollama_dir() == tmp_path / "moved" / "platforms" / "ollama"
    assert platform_deploy.ollama_models_dir() == tmp_path / "moved" / "platforms" / "ollama" / "models"


@pytest.mark.parametrize("rel", ["ollama.exe", "bin/ollama.exe", "bin/ollama"])
def test_portable_ollama_detected(tmp_path, monkeypatch, rel):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _fake_cfg(tmp_path))
    exe = tmp_path / "platforms" / "ollama" / rel
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("x", encoding="utf-8")
    assert platform_deploy.portable_ollama() == str(exe)


def test_portable_ollama_absent(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _fake_cfg(tmp_path))
    assert platform_deploy.portable_ollama() == ""


@pytest.mark.parametrize("base,expect", [
    ("http://127.0.0.1:11434", "127.0.0.1:11434"),
    ("http://127.0.0.1", "127.0.0.1:11434"),
    ("", "127.0.0.1:11434"),
    ("http://0.0.0.0:11500", "0.0.0.0:11500"),
])
def test_host_port(base, expect):
    from backend.services import platform_deploy

    assert platform_deploy._host_port(base) == expect


def test_has_models_detects_blobs(tmp_path):
    from backend.services import platform_deploy

    models = tmp_path / "models"
    assert platform_deploy._has_models(models) is False
    models.mkdir()
    (models / "blobs").mkdir()
    assert platform_deploy._has_models(models) is False
    (models / "blobs" / "sha256-1").write_text("blob", encoding="utf-8")
    assert platform_deploy._has_models(models) is True


def test_detect_marks_platform_managed(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _fake_cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    exe = tmp_path / "platforms" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x", encoding="utf-8")
    monkeypatch.setattr(platform_deploy, "_version", lambda cmd: "ollama version is 0.9.9")
    info = platform_deploy.detect("ollama")
    assert info["installed"] is True
    assert info["managed"] is True
    assert info["path"] == str(exe)
    assert info["models_path"] == str(tmp_path / "platforms" / "ollama" / "models")


def test_detect_marks_system_install_unmanaged(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _fake_cfg(tmp_path))
    monkeypatch.setattr(platform_deploy, "portable_ollama", lambda cfg=None: "")
    monkeypatch.setattr(platform_deploy, "_system_ollama",
                        lambda: r"C:\Users\x\AppData\Local\Programs\Ollama\ollama.exe")
    monkeypatch.setattr(platform_deploy, "_version", lambda cmd: "")
    sys_models = tmp_path / "home" / ".ollama" / "models"
    monkeypatch.setenv("WORKBENCH_OLLAMA_MODELS", "")
    monkeypatch.setattr(platform_deploy, "system_ollama_models_dir", lambda: sys_models)
    info = platform_deploy.detect("ollama")
    assert info["installed"] is True
    assert info["managed"] is False
    assert "Programs" in info["path"]
    # 系统版 Ollama 的模型就在 ~/.ollama/models，不能假装它在 platforms 下
    assert info["models_path"] == str(sys_models)
    assert info["legacy_models"] is False


def test_detect_marks_system_dir_models_as_legacy_after_portable(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _fake_cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    exe = tmp_path / "platforms" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x", encoding="utf-8")
    sys_models = tmp_path / "home" / ".ollama" / "models"
    (sys_models / "blobs").mkdir(parents=True)
    (sys_models / "blobs" / "sha256-a").write_text("b", encoding="utf-8")
    monkeypatch.setattr(platform_deploy, "system_ollama_models_dir", lambda: sys_models)
    monkeypatch.setattr(platform_deploy, "_version", lambda cmd: "")
    info = platform_deploy.detect("ollama")
    assert info["managed"] is True
    assert info["legacy_models"] is True
    assert info["models_path"] == str(tmp_path / "platforms" / "ollama" / "models")
    assert info["system_models_path"] == str(sys_models)


def test_enrich_reports_paths_and_manage_flag(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: {
        **_fake_cfg(tmp_path), "models_dir": str(tmp_path / "models")})
    monkeypatch.setattr(platform_deploy, "detect", lambda key: {
        "installed": True, "path": "C:/Ollama/ollama.exe", "version": "v", "managed": False,
        "models_path": "D:/p/ollama/models", "system_models_path": "", "legacy_models": False,
        "installable": True,
    } if key == "ollama" else {
        "installed": True, "path": "", "version": "", "managed": False, "installable": True,
    })
    items = platform_deploy.enrich([
        {"key": "ollama", "name": "Ollama", "healthy": True},
        {"key": "llama.cpp", "name": "llama.cpp", "healthy": False},
    ])
    ollama = items[0]
    assert ollama["models_path"] == "D:/p/ollama/models"
    assert ollama["install_path"] == "C:/Ollama/ollama.exe"
    assert ollama["managed"] is False
    assert ollama["can_manage"] is True
    assert items[1]["models_path"] == str(tmp_path / "models")


def test_adopt_models_moves_files(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    src = tmp_path / "home" / ".ollama" / "models"
    (src / "blobs").mkdir(parents=True)
    (src / "manifests").mkdir(parents=True)
    (src / "blobs" / "sha256-abc").write_text("blob-data", encoding="utf-8")
    (src / "manifests" / "registry").mkdir()
    (src / "manifests" / "registry" / "qwen").write_text("{}", encoding="utf-8")
    cfg = _fake_cfg(tmp_path)
    exe = tmp_path / "platforms" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("x", encoding="utf-8")
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    monkeypatch.setattr(platform_deploy, "system_ollama_models_dir", lambda: src)
    monkeypatch.setattr(platform_deploy, "PROCS", {})
    monkeypatch.setattr(platform_deploy.platforms, "endpoints", lambda c: {"ollama": "http://127.0.0.1:11434"})

    class _NoProbe:
        async def __call__(self, *a, **kw):
            return False, [], ""

    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", _NoProbe())

    result = __import__("asyncio").run(platform_deploy.adopt_ollama_models())
    assert result["ok"] is True, result
    dst = tmp_path / "platforms" / "ollama" / "models"
    assert (dst / "blobs" / "sha256-abc").read_text(encoding="utf-8") == "blob-data"
    assert (dst / "manifests" / "registry" / "qwen").exists()
    assert not (src / "blobs" / "sha256-abc").exists()


def test_adopt_models_requires_portable(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    src = tmp_path / "home" / ".ollama" / "models"
    (src / "blobs").mkdir(parents=True)
    (src / "blobs" / "sha256-abc").write_text("blob", encoding="utf-8")
    monkeypatch.setattr(platform_deploy, "load_config", lambda: _fake_cfg(tmp_path))
    monkeypatch.setattr(platform_deploy, "system_ollama_models_dir", lambda: src)
    result = __import__("asyncio").run(platform_deploy.adopt_ollama_models())
    assert result["ok"] is False
    assert "装到工作台目录" in result["msg"]


def test_console_deploy_card_shows_dirs():
    root = Path(__file__).resolve().parents[1] / "backend" / "console"
    js = (root / "models.js").read_text(encoding="utf-8")
    assert "platform-path" in js
    assert '["程序"' in js and '["模型"' in js
    assert "data-pdeploy-manage" in js and "data-adopt-models" in js
    session = (root / "session.js").read_text(encoding="utf-8")
    assert "adopt-models" in session
    assert "force=true" in session
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "ollama-windows-amd64.zip" in html


def test_login_remembers_username_without_hardcoded_admin():
    root = Path(__file__).resolve().parents[1]
    console_html = (root / "backend" / "console" / "index.html").read_text(encoding="utf-8")
    assert 'id="u" value="admin"' not in console_html
    assert 'id="rememberUser"' in console_html
    console_core = (root / "backend" / "console" / "core.js").read_text(encoding="utf-8")
    assert "wb_console_username" in console_core and "saveConsoleUser" in console_core
    console_session = (root / "backend" / "console" / "session.js").read_text(encoding="utf-8")
    assert "saveConsoleUser(" in console_session
    front_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="authRemember"' in front_html
    auth_js = (root / "frontend" / "auth.js").read_text(encoding="utf-8")
    assert "wb_last_username" in auth_js and "saveRememberedUsername" in auth_js
