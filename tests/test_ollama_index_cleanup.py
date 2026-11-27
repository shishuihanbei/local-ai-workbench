"""Ollama 拉取后的索引兜底与旧分片清理。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend import ollama_tags
from backend.services import platform_deploy, platform_models


def _cfg(tmp_path: Path) -> dict:
    return {"platforms_dir": str(tmp_path / "platforms"),
            "models_dir": str(tmp_path / "models"),
            "platform_endpoints": {"ollama": "http://127.0.0.1:11434"}}


def _manifest(root: Path, name: str = "foo:1b", digest: str = "sha256-model") -> None:
    model, tag = name.split(":", 1)
    path = root / "manifests" / "registry.ollama.ai" / "library" / model / tag
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schemaVersion": 2,
        "config": {"digest": "sha256:config", "size": 10},
        "layers": [{"mediaType": "application/vnd.ollama.image.model",
                    "digest": "sha256:" + digest.replace("sha256-", ""), "size": 4096}],
    }), encoding="utf-8")


def test_local_tags_reads_manifest_when_api_is_stale(tmp_path, monkeypatch):
    root = tmp_path / "models" / "ollama"
    blobs = root / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "sha256-model").write_bytes(b"x" * 4096)
    (blobs / "sha256-config").write_bytes(b"{}")
    _manifest(root)
    assert ollama_tags.local_tags(root) == ["foo:1b"]

    # manifest 存在、模型层 blob 缺失：只下了一半，不能算已拉取
    (blobs / "sha256-model").unlink()
    assert ollama_tags.local_tags(root) == []


def test_platform_models_merges_disk_manifests(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    root = Path(cfg["models_dir"]) / "ollama"
    blobs = root / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "sha256-model").write_bytes(b"x" * 4096)
    (blobs / "sha256-config").write_bytes(b"{}")
    _manifest(root, "new:1b")
    platform_models.invalidate()

    async def status(*args, **kwargs):
        return [{"key": "ollama", "name": "Ollama", "healthy": True,
                 "base_url": "http://127.0.0.1:11434", "models": ["old:1b"],
                 "homepage": "", "multimodal": "部分"}]

    monkeypatch.setattr(platform_models.platforms, "status", status)
    items = asyncio.run(platform_models.reachable(cfg))
    keys = {m["key"] for m in items}
    assert {"old:1b", "new:1b"} <= keys


def test_cleanup_removes_only_orphan_or_duplicate_partials(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(platform_deploy, "load_config", lambda: cfg)
    platform_deploy.PULL.update(platform_deploy.PULL_FIELDS)
    root = Path(cfg["models_dir"]) / "ollama"
    blobs = root / "blobs"
    blobs.mkdir(parents=True)

    # 真正没人引用的 1GB 旧分片（用户截图里的 1066MB）
    (blobs / "sha256-orphan-partial").write_bytes(b"o" * (1024 * 1024))
    # 完整 blob 已存在，分片只是拉取成功后的残留
    (blobs / "sha256-done").write_bytes(b"d" * 4096)
    (blobs / "sha256-done-partial").write_bytes(b"d" * 4096)
    # manifest 仍引用、完整 blob 缺失：这是可续传数据，不能误删
    (blobs / "sha256-model").write_bytes(b"")
    (blobs / "sha256-model-partial").write_bytes(b"m" * 2048)
    (blobs / "sha256-config").write_bytes(b"{}")
    _manifest(root, "foo:1b")

    preview = platform_deploy.cleanup_orphan_partials(dry_run=True)
    assert preview["count"] == 2
    assert (blobs / "sha256-orphan-partial").exists()  # dry-run 不删

    result = platform_deploy.cleanup_orphan_partials()
    assert result["count"] == 2
    assert result["bytes"] == 1024 * 1024 + 4096
    assert not (blobs / "sha256-orphan-partial").exists()
    assert not (blobs / "sha256-done-partial").exists()
    assert (blobs / "sha256-model-partial").exists(), "manifest 引用的未完成分片要保留给续传"
