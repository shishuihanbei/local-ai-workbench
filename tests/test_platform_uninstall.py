"""平台卸载与 Ollama tag 拉取：删程序、保模型、拒系统安装。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _cfg(tmp_path: Path) -> dict:
    return {"platforms_dir": str(tmp_path / "platforms"),
            "models_dir": str(tmp_path / "models"),
            "llama_dir": str(tmp_path / "platforms" / "llama.cpp"),
            "platform_endpoints": {"ollama": "http://127.0.0.1:11434"}}


def _portable_ollama(root: Path, models: int = 2) -> Path:
    """造一个“工作台装好的 Ollama”：程序 + lib + 用户自己 pull 的模型。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "ollama.exe").write_bytes(b"MZ-fake")
    lib = root / "lib" / "ollama"
    lib.mkdir(parents=True)
    (lib / "ggml.dll").write_bytes(b"dll")
    blobs = root / "models" / "blobs"
    blobs.mkdir(parents=True)
    for i in range(models):
        (blobs / f"sha256-{i}").write_bytes(b"model-data" * 100)
    return root


def test_ollama_uninstall_keeps_user_models(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    root = _portable_ollama(tmp_path / "platforms" / "ollama")
    cache = tmp_path / "platforms" / ".downloads" / platform_deploy.ollama_archive()[1]
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"zip-archive")

    async def not_healthy(*a, **kw):
        return False, [], ""

    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", not_healthy)
    platform_deploy.PROCS.pop("ollama", None)

    result = asyncio.run(platform_deploy.uninstall("ollama"))
    assert result["ok"] is True, result["msg"]
    # 程序与下载缓存都删掉
    assert not (root / "ollama.exe").exists()
    assert not (root / "lib").exists()
    assert not cache.exists()
    # 用户自己 pull 的模型留着，并被收进 models/ollama
    kept = tmp_path / "models" / "ollama"
    assert (kept / "blobs" / "sha256-0").exists()
    assert result["kept_models"] == str(kept)
    assert "模型保留" in result["msg"]
    assert "installers" in result["msg"]
    assert result["freed"] > 0
    assert platform_deploy.get_state("ollama")["msg"].startswith("已卸载")


def test_ollama_uninstall_refuses_system_install(tmp_path, monkeypatch):
    """系统目录里的 Ollama 不是工作台装的，不能由平台卡删。"""
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    monkeypatch.setattr(platform_deploy, "_system_ollama",
                        lambda: str(tmp_path / "Programs" / "Ollama" / "ollama.exe"))
    result = asyncio.run(platform_deploy.uninstall("ollama"))
    assert result["ok"] is False
    assert "系统" in result["msg"]


def test_ollama_uninstall_refuses_running_foreign_service(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    _portable_ollama(tmp_path / "platforms" / "ollama")

    async def healthy(*a, **kw):
        return True, ["llama3:8b"], ""

    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", healthy)
    platform_deploy.PROCS.pop("ollama", None)
    result = asyncio.run(platform_deploy.uninstall("ollama"))
    assert result["ok"] is False
    assert "Quit" in result["msg"]
    assert (tmp_path / "platforms" / "ollama" / "ollama.exe").exists()


def test_llama_uninstall_refuses_outside_platforms(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    cfg["llama_dir"] = str(tmp_path / "somewhere" / "llama.cpp")
    (tmp_path / "somewhere" / "llama.cpp").mkdir(parents=True)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)

    async def no_stop():
        return None

    monkeypatch.setattr(platform_deploy.llama.server, "stop", no_stop)
    monkeypatch.setattr(platform_deploy.subprocess, "run", lambda *a, **kw: None)
    result = asyncio.run(platform_deploy.uninstall("llama.cpp"))
    assert result["ok"] is False
    assert "不在工作台目录" in result["msg"]


def test_llama_uninstall_removes_platform_dir(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    d = tmp_path / "platforms" / "llama.cpp"
    d.mkdir(parents=True)
    (d / "llama-server.exe").write_bytes(b"MZ")
    models = tmp_path / "models"
    models.mkdir()
    (models / "x.gguf").write_bytes(b"gguf")
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)

    stopped = {"n": 0}

    async def no_stop():
        stopped["n"] += 1

    monkeypatch.setattr(platform_deploy.llama.server, "stop", no_stop)
    monkeypatch.setattr(platform_deploy.subprocess, "run", lambda *a, **kw: None)
    result = asyncio.run(platform_deploy.uninstall("llama.cpp"))
    assert result["ok"] is True, result["msg"]
    assert stopped["n"] == 1          # 先停工作台拉起的 llama-server
    assert not d.exists()
    assert (models / "x.gguf").exists()   # 模型目录独立于程序目录，不动
    assert result["kept_models"] == str(models)


def test_uninstall_rejects_unknown_platform(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    assert asyncio.run(platform_deploy.uninstall("nope"))["ok"] is False


def test_ollama_tag_mapping_and_validation():
    from backend import ollama_tags

    assert ollama_tags.tag_for("qwen25-7b") == "qwen2.5:7b"
    assert ollama_tags.tag_for("1.5b") == "deepseek-r1:1.5b"
    assert ollama_tags.tag_for("v4-flash") == ""      # 没有对应 tag 的就不硬凑
    assert ollama_tags.normalize_tag(" qwen2.5:7b ") == "qwen2.5:7b"
    assert ollama_tags.normalize_tag("hf.co/user/repo:Q4_K_M") == "hf.co/user/repo:Q4_K_M"
    for bad in ("", "  ", "-rm", "a b", "rm;del x"):
        with pytest.raises(ValueError):
            ollama_tags.normalize_tag(bad)


def test_pull_requires_running_service(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))

    async def not_healthy(*a, **kw):
        return False, [], ""

    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", not_healthy)
    platform_deploy.PULL.update(running=False, tag="", ok=None, finished_at=0)
    result = asyncio.run(platform_deploy.ollama_pull("qwen2.5:7b"))
    assert result["ok"] is False
    assert "启动" in result["msg"]
    assert platform_deploy.PULL["running"] is False


def test_pull_state_reports_progress(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    platform_deploy.PULL.update(running=True, tag="qwen2.5:7b", pct=42.0, step="下载",
                                msg="下载 1/2 MB", ok=None, started_at=platform_deploy.time.time())
    st = platform_deploy.pull_state()
    assert st["running"] is True and st["tag"] == "qwen2.5:7b" and st["pct"] == 42.0
    assert st["elapsed"] >= 0
    platform_deploy.PULL.update(running=False, pct=0, step="", msg="尚未拉取", tag="")


def test_pull_skips_tag_already_in_ollama(tmp_path, monkeypatch):
    """已经拉过的 tag 直接返回 already，不再启动第二轮下载。"""
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    platform_deploy.PULL.update(platform_deploy.PULL_FIELDS)
    platform_deploy.PULLS.clear()

    async def healthy(*a, **kw):
        return True, [], ""

    async def tags(_base):
        return ["qwen2.5:7b"]

    monkeypatch.setattr(platform_deploy.platforms, "_probe_external", healthy)
    monkeypatch.setattr(platform_deploy, "_ollama_tag_list", tags)
    result = asyncio.run(platform_deploy.ollama_pull("qwen2.5:7b"))
    assert result["ok"] is True
    assert result["already"] is True
    assert "无需重复" in result["msg"]
    assert platform_deploy.PULL["running"] is False
    assert platform_deploy.pull_state("qwen2.5:7b")["step"] == "已存在"


def test_pull_state_is_kept_per_tag(tmp_path, monkeypatch):
    from backend.services import platform_deploy

    monkeypatch.setattr(platform_deploy, "load_config", lambda: _cfg(tmp_path))
    platform_deploy.PULL.update(platform_deploy.PULL_FIELDS)
    platform_deploy.PULLS.clear()
    platform_deploy._pull_set(tag="qwen2.5:7b", running=True, pct=39, step="下载",
                              msg="39/1066 MB", digest="aabd4debf0c8", bytes=39 * 2**20,
                              total=1066 * 2**20)
    one = platform_deploy.pull_state("qwen2.5:7b")
    other = platform_deploy.pull_state("qwen3:8b")
    assert one["running"] is True and one["pct"] == 39 and one["digest"] == "aabd4debf0c8"
    assert other["running"] is False and other["pct"] == 0
    platform_deploy.PULL.update(platform_deploy.PULL_FIELDS)
    platform_deploy.PULLS.clear()


def test_partial_blob_is_detected(tmp_path, monkeypatch):
    """Ollama 中断后留下的 -partial 分片要能被页面提示出来。"""
    from backend.services import platform_deploy

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    blobs = tmp_path / "models" / "ollama" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "sha256-abc-partial").write_bytes(b"x" * (1024 * 1024))
    state = platform_deploy.partial_state()
    assert state["bytes"] == 1024 * 1024
    assert "断点续传" in state["msg"]
