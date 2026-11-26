"""Hugging Face / ModelScope 整仓库模型下载。

需独立引擎的模型通常不是一个 GGUF 文件，而是一整个仓库（config、tokenizer、
多个权重分片）。这里用 huggingface_hub 的 snapshot_download 拉到
<模型目录>/<模型 key> 下，并在完成后写一个标记文件，避免把半成品当成已下载。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from ..config import load_config

_MARKER = ".workbench-downloaded"
_STATE: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _blank(key: str) -> dict[str, Any]:
    return {
        "key": key, "running": False, "ok": False, "error": "", "msg": "",
        "bytes": 0, "total_bytes": 0, "pct": 0,
        "started_at": 0.0, "finished_at": 0.0,
    }


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith(".") or name.endswith(".part"):
                continue
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _set(key: str, **kw: Any) -> None:
    with _LOCK:
        st = _STATE.setdefault(key, _blank(key))
        st.update(kw)


def status(key: str) -> dict[str, Any]:
    cfg = load_config()
    dest = Path(cfg["models_dir"]) / key
    st = dict(_STATE.get(key) or _blank(key))
    st["dir"] = str(dest)
    st["marker"] = (dest / _MARKER).exists()
    size = _dir_bytes(dest)
    st["bytes"] = max(size, int(st.get("bytes") or 0)) if st.get("running") else size
    total = int(st.get("total_bytes") or 0)
    if total > 0:
        st["pct"] = min(100, round(st["bytes"] * 100 / total, 1))
    elif st.get("marker"):
        st["pct"] = 100
    if st.get("marker") and not st.get("running"):
        st["ok"] = True
        st["msg"] = st.get("msg") or "已下载"
    return st


def downloaded(cfg: dict[str, Any], key: str) -> bool:
    return (Path(cfg["models_dir"]) / key / _MARKER).exists()


def partial(cfg: dict[str, Any], key: str) -> bool:
    dest = Path(cfg["models_dir"]) / key
    return dest.exists() and not (dest / _MARKER).exists()


def _total_bytes(repo: str, endpoint: str) -> int:
    try:
        os.environ["HF_ENDPOINT"] = endpoint
        from huggingface_hub import HfApi
        info = HfApi(endpoint=endpoint).model_info(repo, files_metadata=True)
        return sum(int(getattr(s, "size", 0) or 0) for s in (info.siblings or []))
    except Exception:
        return 0


def _run(key: str, repo: str, dest: Path, endpoint: str, token: str) -> None:
    try:
        os.environ["HF_ENDPOINT"] = endpoint
        from huggingface_hub import snapshot_download
        _set(key, msg="正在下载模型文件…", pct=1)
        snapshot_download(
            repo_id=repo,
            local_dir=str(dest),
            max_workers=4,
            token=token or None,
        )
        dest.mkdir(parents=True, exist_ok=True)
        (dest / _MARKER).write_text(repo + "\n", encoding="utf-8")
        size = _dir_bytes(dest)
        _set(key, running=False, ok=True, error="", pct=100,
             bytes=size, finished_at=time.time(), msg=f"下载完成（{repo}）")
    except Exception as exc:  # noqa: BLE001 - 原样回传给界面
        _set(key, running=False, ok=False, error=str(exc)[:500],
             finished_at=time.time(), msg=f"下载失败：{str(exc)[:200]}")


def start(key: str, repo: str) -> dict[str, Any]:
    st = _STATE.get(key) or {}
    if st.get("running"):
        return {"ok": True, "msg": "已在下载中", "state": status(key)}
    cfg = load_config()
    dest = Path(cfg["models_dir"]) / key
    dest.mkdir(parents=True, exist_ok=True)
    endpoint = str(cfg.get("hf_endpoint") or "https://hf-mirror.com").strip()
    token = str(cfg.get("hf_token") or "").strip()
    total = _total_bytes(repo, endpoint)
    init = _blank(key)
    init.pop("key", None)
    _set(key, **init, running=True, total_bytes=total,
         started_at=time.time(), msg="准备下载…")
    threading.Thread(target=_run, args=(key, repo, dest, endpoint, token),
                     daemon=True, name=f"hf-download-{key}").start()
    return {"ok": True, "msg": "已开始下载", "state": status(key)}
