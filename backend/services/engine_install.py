"""独立引擎一键安装（pip）。

只安装 ENGINE_CATALOG 里登记过的包；命令固定、管理员触发，不接受任意命令。
安装过程放到后台线程，前台轮询进度，避免把请求拖死。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any

from . import engines

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}


def _blank(key: str) -> dict[str, Any]:
    return {
        "key": key, "running": False, "ok": False, "error": "", "msg": "",
        "pct": 0, "step": "", "log": "", "started_at": 0.0, "finished_at": 0.0,
    }


def _set(key: str, **kw: Any) -> None:
    with _LOCK:
        st = _STATE.setdefault(key, _blank(key))
        st.update(kw)


def status(key: str) -> dict[str, Any]:
    return dict(_STATE.get(key) or _blank(key))


def running() -> str:
    for key, st in _STATE.items():
        if st.get("running"):
            return key
    return ""


def _run(key: str, packages: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "-U", "--no-input"] + packages
    env = os.environ.copy()
    env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    try:
        from . import platform_store
        env["PIP_CACHE_DIR"] = str(platform_store.pip_cache())
        env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(platform_store.tmp_root())
        env["HF_HOME"] = str(platform_store.hf_home())
    except Exception:
        pass
    creationflags = 0x08000000 if os.name == "nt" else 0
    tail: list[str] = []
    try:
        _set(key, pct=5, step="启动 pip", msg="正在安装 " + "、".join(packages))
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
            creationflags=creationflags,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            tail.append(line[:300])
            tail = tail[-8:]
            low = line.lower()
            pct, step = 30, "下载依赖"
            if "collecting" in low:
                pct, step = 15, "解析依赖"
            elif "downloading" in low:
                pct, step = 40, "下载安装包"
            elif "installing collected" in low or "successfully installed" in low:
                pct, step = 80, "写入环境"
            _set(key, pct=pct, step=step, msg=line[:300], log="\n".join(tail))
        code = proc.wait()
        import importlib
        importlib.invalidate_caches()
        st = engines.status()
        installed = bool(st.get("installed", {}).get(key))
        if code == 0 and installed:
            _set(key, running=False, ok=True, error="", pct=100,
                 step="完成", msg=f"{engines.ENGINE_CATALOG[key]['label']} 安装成功",
                 finished_at=time.time(), log="\n".join(tail))
        else:
            reason = "安装命令结束，但没有检测到引擎" if code == 0 else f"pip 退出码 {code}"
            _set(key, running=False, ok=False, error=reason,
                 step="失败", msg=f"安装失败：{reason}", finished_at=time.time(),
                 log="\n".join(tail))
    except Exception as exc:  # noqa: BLE001 - 原样回传
        _set(key, running=False, ok=False, error=str(exc)[:500], step="失败",
             msg=f"安装失败：{str(exc)[:200]}", finished_at=time.time(),
             log="\n".join(tail))


def start(key: str) -> dict[str, Any]:
    info = engines.ENGINE_CATALOG.get(key)
    if not info:
        raise ValueError("未知的独立引擎")
    state = engines.status()
    if state.get("installed", {}).get(key):
        raise ValueError(f"{info['label']} 已经安装，不需要重复安装")
    if key == "vllm" and str(state.get("platform") or "").lower() == "windows":
        raise ValueError("Windows 不能直接一键安装 vLLM，请用 WSL2 或 Linux 机器；也可以先装 Transformers")
    packages = list(info.get("pip") or [])
    if not packages:
        raise ValueError(f"{info['label']} 没有可靠的 pip 安装包，请按“安装方法”手动安装")
    busy = running()
    if busy:
        raise ValueError(f"已有引擎（{busy}）正在安装，请等它完成再试")
    init = _blank(key)
    init.pop("key", None)
    _set(key, **init, running=True, pct=1, step="准备",
         started_at=time.time(), msg="正在准备安装…")
    threading.Thread(target=_run, args=(key, packages), daemon=True,
                     name=f"engine-install-{key}").start()
    return {"ok": True, "msg": "已开始安装", "state": status(key)}
