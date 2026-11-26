"""Ollama 便携部署流程：解压结构、模型目录环境变量、启动参数。"""
from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest


def _fake_windows_zip(path: Path) -> Path:
    """照 Windows 官方 zip 的结构造一个小包：ollama.exe + lib/ollama/*.dll。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ollama.exe", b"MZ-fake")
        zf.writestr("lib/ollama/runners/cpu/ggml.dll", b"dll")
    return path


def _cfg(tmp_path: Path) -> dict:
    return {"platforms_dir": str(tmp_path / "platforms"), "models_dir": str(tmp_path / "models"),
            "platform_endpoints": {"ollama": "http://127.0.0.1:11434", "vllm": "http://127.0.0.1:8000",
                                   "lmstudio": "http://127.0.0.1:1234", "custom": "http://127.0.0.1:8001"}}


def test_extract_keeps_nested_lib(tmp_path):
    from backend.services import platform_deploy

    archive = _fake_windows_zip(tmp_path / "ollama-windows-amd64.zip")
    target = tmp_path / "platforms" / "ollama"
    platform_deploy._extract_archive(archive, target)
    assert (target / "ollama.exe").read_bytes() == b"MZ-fake"
    assert (target / "lib" / "ollama" / "runners" / "cpu" / "ggml.dll").read_bytes() == b"dll"


def test_extract_rejects_zip_slip(tmp_path):
    from backend.services import platform_deploy

    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.exe", b"x")
    with pytest.raises(RuntimeError):
        platform_deploy._extract_archive(archive, tmp_path / "target")


def test_install_flow_uses_cache_and_sets_models_dir(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    cache = tmp_path / "platforms" / ".downloads" / "ollama-windows-amd64.zip"
    _fake_windows_zip(cache)

    async def no_download(key, url, dest):
        raise AssertionError("已有缓存时不该再下载")

    monkeypatch.setattr(platform_deploy, "_download_file", no_download)
    ok, msg = asyncio.run(platform_deploy._install_ollama("ollama", force=False))
    assert ok is True, msg
    exe = tmp_path / "platforms" / "ollama" / "ollama.exe"
    assert exe.exists()
    assert (tmp_path / "platforms" / "ollama" / "models").is_dir()
    state = platform_deploy.get_state("ollama")
    assert "platforms" in state["msg"] or "程序" in state["msg"]


def test_install_flow_reports_after_extract(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    cache = tmp_path / "platforms" / ".downloads" / "ollama-windows-amd64.zip"

    async def fake_download(key, url, dest):
        _fake_windows_zip(dest)

    monkeypatch.setattr(platform_deploy, "_download_file", fake_download)
    ok, msg = asyncio.run(platform_deploy._install_ollama("ollama", force=True))
    assert ok is True, msg
    assert "platforms/ollama" in msg or "platforms\\ollama" in msg


def test_start_passes_models_env(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    monkeypatch.setattr(platform_deploy, "LOG_DIR", tmp_path / "logs")
    exe = tmp_path / "platforms" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    seen: dict = {}

    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        seen["env"] = kw.get("env") or {}
        return FakeProc()

    async def healthy(*a, **kw):
        return bool(seen.get("cmd")), [], ""

    monkeypatch.setattr(platform_deploy.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", healthy)
    ok, msg = asyncio.run(platform_deploy._start_ollama("ollama", "", force=True))
    assert ok is True, msg
    assert seen["cmd"][0] == str(exe)
    assert seen["cmd"][1] == "serve"
    assert seen["env"]["OLLAMA_MODELS"] == str(tmp_path / "platforms" / "ollama" / "models")
    assert seen["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
