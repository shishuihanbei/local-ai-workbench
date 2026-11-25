"""本地平台单平台一键部署：检测、跳过已安装、安装并启动。

llama.cpp 由工作台自己管理；Ollama / LM Studio 优先用 winget 静默安装，
没有 winget 时回退官方安装包；vLLM 只在 Linux 上安装；自定义平台只做连接测试。
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import CREATE_NO_WINDOW, DATA_DIR, IS_WINDOWS, load_config
from ..db import fetch_all
from . import hardware, installer, llama, platforms

STATE: dict[str, dict[str, Any]] = {}
PROCS: dict[str, subprocess.Popen] = {}
LOG_DIR = DATA_DIR / "logs"


def _blank() -> dict[str, Any]:
    return {"running": False, "ok": None, "skipped": False, "pct": 0, "step": "",
            "msg": "尚未部署", "error": "", "started_at": 0, "finished_at": 0}


def _state(key: str) -> dict[str, Any]:
    return STATE.setdefault(key, _blank())


def _set(key: str, **kw) -> None:
    _state(key).update(kw)


def get_state(key: str) -> dict[str, Any]:
    st = dict(_state(key))
    if key == "llama.cpp":
        inst = installer.STATE
        if inst.get("running") or (st.get("running") and inst.get("finished_at", 0) >= st.get("started_at", 0)):
            for field in ("running", "ok", "pct", "step", "msg", "error", "sha256", "bytes", "finished_at"):
                if field in inst:
                    st[field] = inst[field]
            if inst.get("running"):
                st["running"] = True
    return st


def is_running(key: str) -> bool:
    return bool(_state(key).get("running"))


def _which(*names: str) -> str:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def _exists(*paths: str) -> str:
    for raw in paths:
        p = Path(os.path.expandvars(raw)).expanduser()
        if p.exists():
            return str(p)
    return ""


def _winget() -> str:
    if not IS_WINDOWS:
        return ""
    return _which("winget") or _exists(
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe",
        r"%ProgramFiles%\WindowsApps\winget.exe",
    )


def _local_installer(keyword: str, suffix: str) -> str:
    folder = DATA_DIR / "installers"
    if not folder.exists():
        return ""
    found = [p for p in folder.iterdir()
             if p.is_file() and keyword in p.name.lower() and p.suffix.lower() == suffix]
    return str(max(found, key=lambda p: p.stat().st_mtime)) if found else ""


def _version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=8, creationflags=CREATE_NO_WINDOW)
        text = (out.stdout or out.stderr or "").strip().splitlines()
        for line in text:
            low = line.lower()
            if any(ch.isdigit() for ch in line) and any(k in low for k in ("version", "ollama", "lm studio", "vllm")):
                return line[:120]
        return (text[0][:120] if text else "")
    except Exception:
        return ""


def detect(key: str) -> dict[str, Any]:
    """只做本机检测，不联网、不安装。"""
    if key == "llama.cpp":
        info = hardware.llama_info()
        return {"installed": bool(info.get("installed")), "path": info.get("path", ""),
                "version": info.get("version", ""), "installable": True}
    if key == "ollama":
        path = _which("ollama") or _exists(
            r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe",
            r"%LOCALAPPDATA%\Ollama\ollama.exe",
            r"%ProgramFiles%\Ollama\ollama.exe",
            "/usr/local/bin/ollama", "/usr/bin/ollama",
            "~/.local/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama",
        )
        return {"installed": bool(path), "path": path, "version": _version([path, "--version"]) if path else "",
                "installable": True}
    if key == "vllm":
        path = _which("vllm")
        spec = bool(importlib.util.find_spec("vllm"))
        return {"installed": bool(path or spec), "path": path or ("python 包" if spec else ""),
                "version": _version([path, "--version"]) if path else "",
                "installable": platform.system().lower() == "linux"}
    if key == "lmstudio":
        path = _which("lms") or _exists(
            r"%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe",
            r"%LOCALAPPDATA%\LM Studio\LM Studio.exe",
            r"%ProgramFiles%\LM Studio\LM Studio.exe",
            "/Applications/LM Studio.app",
            "~/.local/bin/lm-studio",
        )
        return {"installed": bool(path), "path": path, "version": "",
                "installable": platform.system().lower() in ("windows", "darwin")}
    return {"installed": None, "path": "", "version": "", "installable": False}


def enrich(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把安装状态、按钮文案和进度补到平台卡片上。"""
    for item in items:
        key = item["key"]
        info = detect(key)
        item["installed"] = bool(info["installed"]) or bool(item.get("healthy"))
        item["install_path"] = info.get("path", "")
        item["version"] = info.get("version", "")
        item["installable"] = bool(info.get("installable")) or key == "llama.cpp"
        item["install"] = get_state(key)
        if key == "custom":
            item["action"] = "test"
            item["action_label"] = "测试连接"
            item["deployable"] = True
        elif key == "vllm" and not info.get("installable"):
            item["action"] = "guide"
            item["action_label"] = "仅 Linux · 说明"
            item["deployable"] = True
        elif item.get("healthy"):
            item["action"] = "running"
            item["action_label"] = "已运行"
            item["deployable"] = False
        elif item["installed"]:
            item["action"] = "start"
            item["action_label"] = "启动"
            item["deployable"] = True
        elif item["installable"]:
            item["action"] = "install"
            item["action_label"] = "一键部署"
            item["deployable"] = True
        else:
            item["action"] = "manual"
            item["action_label"] = "查看安装"
            item["deployable"] = False
    return items


def _tail(text: str, limit: int = 300) -> str:
    lines = [line.strip() for line in (text or "").replace("\r", "").splitlines() if line.strip()]
    return lines[-1][:limit] if lines else ""


def _run(key: str, cmd: list[str], timeout: int = 1800, env: dict | None = None) -> None:
    """在线程里跑安装命令，避免卡住事件循环。"""
    _set(key, msg=_tail(" ".join(cmd), 200))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, env=env,
                                creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"安装超时（{timeout // 60} 分钟）") from exc
    if result.returncode != 0:
        tail = _tail((result.stderr or "") + "\n" + (result.stdout or ""))
        raise RuntimeError(f"安装命令失败（退出码 {result.returncode}）：{tail or '没有输出'}")
    tail = _tail(result.stdout or "")
    if tail:
        _set(key, msg=tail)


async def _install_winget(key: str, package_id: str) -> bool:
    winget = _winget()
    if not winget:
        return False
    _set(key, step="安装", msg=f"winget 安装 {package_id}")
    await asyncio.to_thread(
        _run, key,
        [winget, "install", "--id", package_id, "--exact", "--silent",
         "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"],
    )
    return True


async def _download_file(key: str, url: str, dest: Path) -> None:
    def progress(done: int, total: int, note: str) -> None:
        pct = 8 + round(min(done / total, 0.99) * 45, 1) if total else 15
        _set(key, pct=pct, msg=f"{note}下载 {done/2**20:.0f}/{total/2**20:.0f} MB" if total else note)
    await installer._download(url, dest, on_progress=progress)


async def _install_ollama(key: str) -> tuple[bool, str]:
    if IS_WINDOWS:
        setup = _local_installer("ollama", ".exe")
        if setup:
            _set(key, step="本地包", msg=f"使用本地安装包 {Path(setup).name}")
            await asyncio.to_thread(_run, key, [setup, "/VERYSILENT", "/NORESTART", "/SP-"], 900)
        else:
            started = False
            try:
                started = await _install_winget(key, "Ollama.Ollama")
            except Exception as exc:
                _set(key, step="回退", msg=f"winget 不可用：{exc}")
            if not started:
                exe = Path(os.environ.get("TEMP", ".")) / "OllamaSetup.exe"
                _set(key, step="下载", msg="从 Ollama 官网下载安装包")
                await _download_file(key, "https://ollama.com/download/OllamaSetup.exe", exe)
                _set(key, step="安装", msg="静默安装 Ollama")
                await asyncio.to_thread(_run, key,
                                        [str(exe), "/VERYSILENT", "/NORESTART", "/SP-"], 900)
    else:
        _set(key, step="安装", msg="Linux 安装 Ollama（需要当前用户可写 ~/.local）")
        tmp = Path(os.environ.get("TEMP", "/tmp")) / "ollama-install.sh"
        await _download_file(key, "https://ollama.com/install.sh", tmp)
        await asyncio.to_thread(_run, key, ["sh", str(tmp)], 900)
    info = detect(key)
    if not info["installed"]:
        return False, "安装完成但没找到 ollama 命令，可能需要重新打开工作台或手动安装"
    return True, "Ollama 已安装"


async def _start_ollama(key: str, endpoint: str = "") -> tuple[bool, str]:
    cfg = load_config()
    base = endpoint or platforms.endpoints(cfg).get("ollama", "")
    healthy, _, _ = await platforms._probe_external(base, "/api/tags")
    if healthy:
        return True, "Ollama 已在运行，跳过启动"
    exe = detect("ollama")["path"]
    if not exe:
        return False, "没有找到 ollama 命令"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "ollama.log", "a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("OLLAMA_HOST", "127.0.0.1:11434")
    flags = CREATE_NO_WINDOW if IS_WINDOWS else 0
    PROC = subprocess.Popen([exe, "serve"], stdout=log, stderr=subprocess.STDOUT,
                            creationflags=flags, env=env)
    PROCS[key] = PROC
    for _ in range(20):
        await asyncio.sleep(1)
        healthy, _, _ = await platforms._probe_external(base, "/api/tags")
        if healthy:
            return True, f"Ollama 已启动（PID {PROC.pid}）"
    return False, "Ollama 进程已启动，但端口还没响应，请查看 data/logs/ollama.log"


async def _deploy_ollama(key: str, endpoint: str = "") -> tuple[bool, str, bool]:
    info = detect(key)
    skipped = bool(info["installed"])
    if skipped:
        _set(key, step="跳过安装", msg="本机已安装 Ollama，跳过下载与安装")
    else:
        _set(key, pct=8, step="安装", msg="开始安装 Ollama")
        ok, msg = await _install_ollama(key)
        if not ok:
            return False, msg, False
    ok, msg = await _start_ollama(key, endpoint)
    return ok, msg, skipped


async def _install_lmstudio(key: str) -> tuple[bool, str, bool]:
    info = detect(key)
    if info["installed"]:
        _set(key, step="跳过安装", msg="本机已安装 LM Studio，跳过下载")
        return True, "LM Studio 已安装", True
    if not _winget():
        return False, "本机没有 winget，无法静默安装 LM Studio；请点“官网”手动下载，或安装 winget 后重试", False
    _set(key, pct=8, step="安装", msg="winget 安装 LM Studio")
    await _install_winget(key, "ElementLabs.LMStudio")
    info = detect(key)
    if not info["installed"]:
        return False, "安装完成但没找到 LM Studio，请重新打开工作台或查看安装目录", False
    return True, "LM Studio 已安装", False


async def _deploy_lmstudio(key: str, endpoint: str = "") -> tuple[bool, str, bool]:
    ok, msg, skipped = await _install_lmstudio(key)
    if not ok:
        return False, msg, skipped
    base = endpoint or platforms.endpoints(load_config()).get("lmstudio", "")
    healthy, _, _ = await platforms._probe_external(base, "/v1/models")
    if healthy:
        return True, "LM Studio 本地服务已连接", skipped
    info = detect("lmstudio")
    if IS_WINDOWS and info.get("path", "").lower().endswith(".exe"):
        flags = CREATE_NO_WINDOW
        try:
            subprocess.Popen([info["path"]], creationflags=flags)
        except Exception:
            pass
    return True, "LM Studio 已安装并打开；请在 Developer 页开启 Local Server 后再点“更新”", skipped


async def _deploy_vllm(key: str) -> tuple[bool, str, bool]:
    if platform.system().lower() != "linux":
        return False, "vLLM 官方主要支持 Linux + NVIDIA GPU；Windows 请使用 WSL2 或单独服务器，本机不能直接一键部署", False
    info = detect(key)
    if info["installed"]:
        return True, "vLLM 已安装，跳过安装；请用命令行启动 vLLM 服务", True
    _set(key, pct=8, step="安装", msg="pip 安装 vLLM（下载较大，请耐心等待）")
    env = os.environ.copy()
    env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    await asyncio.to_thread(_run, key, [sys.executable, "-m", "pip", "install", "-U", "vllm"], 2400, env)
    if not detect(key)["installed"]:
        return False, "pip 安装结束但没检测到 vLLM，请查看控制台日志", False
    return True, "vLLM 已安装；请用 vllm serve 指定模型后启动", False


async def _pick_local_model(cfg: dict) -> dict | None:
    from ..config import model_file_path
    rows = await fetch_all("SELECT * FROM models ORDER BY sort,key")
    preferred = str(cfg.get("model") or "")
    if preferred:
        rows = [r for r in rows if preferred in (r["key"], r.get("alias"), r.get("label"))] + \
               [r for r in rows if preferred not in (r["key"], r.get("alias"), r.get("label"))]
    for row in rows:
        path = model_file_path(cfg, row["filename"])
        expected = int(row["total_bytes"] or 0)
        if not path.exists():
            continue
        if expected and path.stat().st_size + 1024 < expected:
            continue
        return row
    return None


async def _deploy_llama(key: str, force: bool = False) -> tuple[bool, str, bool]:
    info = hardware.llama_info()
    skipped = bool(info.get("installed")) and not force
    if skipped:
        _set(key, step="跳过安装", msg="本机已安装 llama.cpp，跳过下载")
    else:
        _set(key, pct=1, step="安装", msg="开始下载 llama.cpp")
        result = await installer.install_llama()
        if not result.get("ok"):
            return False, result.get("msg") or "llama.cpp 安装失败", False
    srv = await llama.server.status()
    if srv.get("healthy"):
        return True, "llama.cpp 已安装并在运行", skipped
    cfg = load_config()
    row = await _pick_local_model(cfg)
    if not row:
        return True, "llama.cpp 已安装；还没有下载完整的 GGUF 模型，请到“模型”页下载后再加载", skipped
    ok, msg = await llama.server.start(row["key"])
    return ok, (msg if ok else f"llama.cpp 启动失败：{msg}"), skipped


async def _deploy_custom(key: str, endpoint: str = "") -> tuple[bool, str, bool]:
    base = endpoint or platforms.endpoints(load_config()).get("custom", "")
    healthy, models, detail = await platforms._probe_external(base, "/v1/models")
    if healthy:
        return True, f"连接正常 · {len(models)} 个模型", False
    return False, detail, False


async def deploy(key: str, force: bool = False, endpoint: str = "") -> dict:
    if key not in platforms.PLATFORMS:
        return {"ok": False, "msg": "未知平台"}
    if _state(key).get("running"):
        return {"ok": False, "msg": "这个平台正在部署，请稍等"}
    endpoint = str(endpoint or "").strip()[:300].rstrip("/")
    if endpoint.endswith("/v1"):
        endpoint = endpoint[:-3]
    now = time.time()
    STATE[key] = {**_blank(), "running": True, "pct": 3, "step": "检测",
                  "msg": "正在检查本机是否已安装", "started_at": now}
    try:
        if key == "llama.cpp":
            ok, msg, skipped = await _deploy_llama(key, force)
        elif key == "ollama":
            ok, msg, skipped = await _deploy_ollama(key, endpoint)
        elif key == "lmstudio":
            ok, msg, skipped = await _deploy_lmstudio(key, endpoint)
        elif key == "vllm":
            ok, msg, skipped = await _deploy_vllm(key)
        elif key == "custom":
            ok, msg, skipped = await _deploy_custom(key, endpoint)
        else:
            ok, msg, skipped = False, "不支持这个平台", False
        _set(key, running=False, ok=ok, skipped=skipped,
             pct=100 if ok else (get_state(key).get("pct") or 3), step="完成" if ok else "失败",
             msg=msg, error="" if ok else msg, finished_at=time.time())
        return {"ok": ok, "msg": msg, "skipped": skipped, "state": get_state(key)}
    except Exception as exc:
        _set(key, running=False, ok=False, step="失败", msg=f"部署失败：{exc}",
             error=str(exc), finished_at=time.time())
        return {"ok": False, "msg": str(exc), "state": get_state(key)}
