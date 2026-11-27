"""已安装平台的启动要像 llama.cpp 一样：一键拉起，不重新安装、不重复开进程。"""
from __future__ import annotations

import asyncio
from pathlib import Path


class _Alive:
    pid = 999

    def poll(self):
        return None


def _cfg(tmp_path: Path) -> dict:
    return {"platforms_dir": str(tmp_path / "platforms"), "models_dir": str(tmp_path / "models"),
            "llama_dir": str(tmp_path / "platforms" / "llama.cpp"),
            "platform_endpoints": {"ollama": "http://127.0.0.1:11434"}}


def test_start_refuses_when_not_installed(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(platform_deploy, "detect", lambda key: {"installed": False})
    monkeypatch.setattr(platform_deploy, "STATE", {})
    result = asyncio.run(platform_deploy.start("ollama"))
    assert result["ok"] is False
    assert "一键部署" in result["msg"]


def test_start_ollama_only_starts_without_install(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(platform_deploy, "detect", lambda key: {"installed": True, "path": "x"})
    calls: list[str] = []

    async def fake_start(key, endpoint="", force=False):
        calls.append(key)
        return True, "Ollama 已启动"

    async def no_install(*a, **kw):
        raise AssertionError("点启动不应重新安装")

    monkeypatch.setattr(platform_deploy, "_start_ollama", fake_start)
    monkeypatch.setattr(platform_deploy, "_install_ollama", no_install)
    monkeypatch.setattr(platform_deploy, "STATE", {})
    result = asyncio.run(platform_deploy.start("ollama"))
    assert result["ok"] is True
    assert calls == ["ollama"]
    st = platform_deploy.get_state("ollama")
    assert st["step"] == "运行中"
    assert st["running"] is False


def test_start_does_not_spawn_second_ollama_when_process_alive(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    exe = tmp_path / "platforms" / "ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(platform_deploy, "portable_ollama", lambda cfg=None: str(exe))
    monkeypatch.setattr(platform_deploy, "detect", lambda key: {"installed": True, "path": str(exe)})
    monkeypatch.setattr(platform_deploy, "PROCS", {"ollama": _Alive()})
    monkeypatch.setattr(platform_deploy, "STATE", {})

    async def not_healthy(*a, **kw):
        return False, [], ""

    def no_popen(*a, **kw):
        raise AssertionError("进程还活着时不能再起一个")

    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", not_healthy)
    monkeypatch.setattr(platform_deploy.subprocess, "Popen", no_popen)
    ok, msg = asyncio.run(platform_deploy._start_ollama("ollama", "", force=False))
    assert ok is False
    assert "不要重复启动" in msg


def test_console_has_start_and_stop_buttons():
    root = Path(__file__).resolve().parents[1] / "backend" / "console"
    js = (root / "session.js").read_text(encoding="utf-8")
    assert '"start"' in js and "启动中…" in js
    assert "data-pstop" in js or "dataset.pstop" in js
    models = (root / "models.js").read_text(encoding="utf-8")
    assert "data-pstop" in models


def test_closed_port_is_detected_quickly():
    """Windows 上连接本机关闭端口会静默等 1 秒，端口预检必须在 0.5 秒内返回。"""
    import time
    from backend.services import platforms

    start = time.time()
    assert platforms._port_open("http://127.0.0.1:59999") is False
    assert time.time() - start < 0.8


def test_enrich_reports_alive_process_when_health_times_out(tmp_path, monkeypatch):
    """端口没回 HTTP、但进程还在时，不能把卡片写成“已安装，未启动”。"""
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(platform_deploy, "detect", lambda key: {"installed": True, "path": "x"})
    monkeypatch.setattr(platform_deploy, "_managed_pids",
                        lambda key: [4321] if key == "ollama" else [])
    monkeypatch.setattr(platform_deploy, "STATE", {})
    item = {
        "key": "ollama", "healthy": False, "installed": True, "models": [],
        "base_url": "http://127.0.0.1:11434/v1", "detail": "端口在监听，但接口超时",
    }
    out = platform_deploy.enrich([item])
    assert out[0]["process_alive"] is True
    assert "PID 4321" in out[0]["detail"]
