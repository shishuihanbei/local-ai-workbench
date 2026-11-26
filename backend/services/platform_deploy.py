"""本地平台单平台一键部署：检测、跳过已安装、安装并启动。

llama.cpp 由工作台自己管理，装在 platforms/llama.cpp；Ollama 也装成便携版，
程序与模型统一放在 platforms/ollama（模型目录通过 OLLAMA_MODELS 指过去）；
LM Studio 优先用 winget 静默安装，没有 winget 时回退官方安装包；
vLLM 只在 Linux 上安装；自定义平台只做连接测试。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import zipfile
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


def _platforms_root(cfg: dict[str, Any]) -> Path:
    return Path(str(cfg.get("platforms_dir") or "")).expanduser()


def ollama_dir(cfg: dict[str, Any] | None = None) -> Path:
    """Ollama 便携版的落位目录：跟着 platforms_dir 走，可用 WORKBENCH_OLLAMA_DIR 覆盖。"""
    env = os.getenv("WORKBENCH_OLLAMA_DIR")
    if env:
        return Path(env).expanduser()
    cfg = cfg or load_config()
    return _platforms_root(cfg) / "ollama"


def ollama_models_dir(cfg: dict[str, Any] | None = None) -> Path:
    """Ollama 的模型目录：默认与程序一起放在 <platforms_dir>/ollama/models。"""
    env = os.getenv("WORKBENCH_OLLAMA_MODELS")
    if env:
        return Path(env).expanduser()
    return ollama_dir(cfg) / "models"


def system_ollama_models_dir() -> Path:
    """系统版 Ollama 的默认模型目录（~/.ollama/models），用于迁移提示。"""
    return Path(os.path.expandvars(os.path.expanduser("~/.ollama/models")))


OLLAMA_PORTABLE_CANDIDATES = (
    "ollama.exe", "bin/ollama.exe", "ollama", "bin/ollama",
    "Ollama.app/Contents/Resources/ollama",
)


def portable_ollama(cfg: dict[str, Any] | None = None) -> str:
    """工作台自己管的便携版 Ollama（platforms/ollama 下），没有就返回空串。"""
    root = ollama_dir(cfg)
    for rel in OLLAMA_PORTABLE_CANDIDATES:
        p = root / rel
        if p.is_file():
            return str(p)
    return ""


def _system_ollama() -> str:
    """系统目录里装的 Ollama（LocalAppData / Program Files / /usr/local/bin 等）。"""
    return _which("ollama") or _exists(
        r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe",
        r"%LOCALAPPDATA%\Ollama\ollama.exe",
        r"%ProgramFiles%\Ollama\ollama.exe",
        "/usr/local/bin/ollama", "/usr/bin/ollama",
        "~/.local/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama",
    )


def ollama_archive() -> tuple[str, str]:
    """便携包下载地址与文件名后缀：官方 zip / tgz，解压即用，不写注册表。"""
    system = platform.system().lower()
    if system == "windows":
        return "https://ollama.com/download/ollama-windows-amd64.zip", "ollama-windows-amd64.zip"
    if system == "darwin":
        return "https://ollama.com/download/Ollama-darwin.zip", "Ollama-darwin.zip"
    return "https://ollama.com/download/ollama-linux-amd64.tgz", "ollama-linux-amd64.tgz"


def _extract_archive(archive: Path, target: Path) -> None:
    """校验压缩包后整包解压到 target，保留内部目录结构（lib/、bin/ 都要）。"""
    tmp = Path(tempfile.mkdtemp(prefix="ollama-install-"))
    try:
        if archive.name.endswith(".tgz") or archive.name.endswith(".tar.gz"):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    parts = Path(member.name).parts
                    if Path(member.name).is_absolute() or ".." in parts:
                        raise RuntimeError("安装包包含不安全路径")
                tf.extractall(tmp, filter="data")
        else:
            with zipfile.ZipFile(archive) as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"安装包压缩校验失败：{bad}")
                for name in zf.namelist():
                    parts = Path(name).parts
                    if Path(name).is_absolute() or ".." in parts:
                        raise RuntimeError("安装包包含不安全路径")
                zf.extractall(tmp)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tmp, target, dirs_exist_ok=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _has_models(folder: Path) -> bool:
    """目录里是否已经有模型文件（blobs 或 manifests 任意一个有内容就算）。"""
    try:
        if not folder.exists():
            return False
        for sub in ("blobs", "manifests"):
            d = folder / sub
            if d.exists() and any(p.is_file() for p in d.rglob("*")):
                return True
        return any(p.is_file() for p in folder.iterdir())
    except Exception:
        return False


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
        cfg = load_config()
        portable = portable_ollama(cfg)
        sys_exe = _system_ollama()
        path = portable or sys_exe
        sys_models = system_ollama_models_dir()
        have_sys_models = _has_models(sys_models)
        # 便携版看 platforms/ollama/models；系统版就是用 ~/.ollama/models，别显示成没装到的地方
        models = ollama_models_dir(cfg) if portable else (sys_models if sys_exe else ollama_models_dir(cfg))
        return {"installed": bool(path), "path": path, "managed": bool(portable),
                "models_path": str(models), "system_models_path": str(sys_models),
                "legacy_models": have_sys_models and bool(portable),
                "version": _version([path, "--version"]) if path else "",
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
    cfg = load_config()
    for item in items:
        key = item["key"]
        info = detect(key)
        item["installed"] = bool(info["installed"]) or bool(item.get("healthy"))
        item["install_path"] = info.get("path", "")
        item["version"] = info.get("version", "")
        item["managed"] = bool(info.get("managed"))
        item["models_path"] = info.get("models_path", "")
        item["legacy_models_path"] = info.get("system_models_path", "") if (
            info.get("legacy_models") and info.get("managed")) else ""
        item["installable"] = bool(info.get("installable")) or key == "llama.cpp"
        item["install"] = get_state(key)
        item["can_manage"] = key == "ollama" and bool(item["installed"]) and not item["managed"]
        if key == "llama.cpp":
            item["models_path"] = str(cfg.get("models_dir") or "")
        if key == "ollama":
            item["target_path"] = str(ollama_dir(cfg))
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


async def _install_ollama(key: str, force: bool = False) -> tuple[bool, str]:
    """把 Ollama 装成便携版：解压到 platforms/ollama，模型放 platforms/ollama/models。

    不写系统目录、不注册服务，整个 platforms 文件夹可以直接搬走。
    """
    cfg = load_config()
    portable = portable_ollama(cfg)
    if portable and not force:
        _set(key, step="跳过安装", msg=f"已使用工作台目录里的 Ollama：{portable}")
        return True, "Ollama 便携版已就位"
    target = ollama_dir(cfg)
    url, name = ollama_archive()
    cache = _platforms_root(cfg) / ".downloads" / name
    cache.parent.mkdir(parents=True, exist_ok=True)
    local_arc = ""
    for suffix in (".zip", ".tgz"):
        local_arc = local_arc or _local_installer("ollama", suffix)
    try:
        if local_arc and not (cache.exists() and cache.stat().st_size > 0):
            archive = Path(local_arc)
            _set(key, pct=60, step="本地包", msg=f"使用本地便携包 {archive.name}")
        else:
            archive = cache
            if cache.exists() and cache.stat().st_size > 0 and force:
                cache.unlink()
            if cache.exists() and cache.stat().st_size > 0:
                _set(key, pct=60, step="本地缓存", msg=f"使用已下载的 {name}")
            else:
                _set(key, pct=8, step="下载", msg=f"下载便携版 {name}")
                await _download_file(key, url, cache)
        _set(key, pct=70, step="解压", msg=f"解压到 {target}")
        await asyncio.to_thread(_extract_archive, archive, target)
    except Exception as exc:
        # 便携版失败时，先退系统里已有的 Ollama，再退 data/installers 里的 OllamaSetup.exe
        sys_exe = _system_ollama()
        if sys_exe:
            _set(key, step="回退", msg=f"便携版安装失败（{exc}），先用系统里的 Ollama：{sys_exe}")
            return True, "便携版下载失败，已退回系统 Ollama"
        setup = _local_installer("ollama", ".exe")
        if setup:
            _set(key, step="回退", msg=f"便携版安装失败（{exc}），改用本地安装包 {Path(setup).name}")
            await asyncio.to_thread(_run, key, [setup, "/VERYSILENT", "/NORESTART", "/SP-"], 900)
            if _system_ollama():
                return True, "已用本地安装包装到系统目录（如需统一目录请重试便携版）"
        return False, f"便携版下载/解压失败：{exc}"
    exe = portable_ollama(cfg)
    if not exe:
        return False, f"解压完成但没在 {target} 里找到 ollama 程序，请检查安装包结构"
    if not IS_WINDOWS:
        try:
            Path(exe).chmod(0o755)
        except Exception:
            pass
    models = ollama_models_dir(cfg)
    models.mkdir(parents=True, exist_ok=True)
    _set(key, pct=88, step="安装", msg=f"程序 {exe} · 模型目录 {models}")
    return True, "Ollama 便携版已装到 platforms/ollama"


def _host_port(base: str, default_port: int = 11434) -> str:
    try:
        parts = urllib.parse.urlsplit(base or "")
        host = parts.hostname or "127.0.0.1"
        port = parts.port or default_port
        return f"{host}:{port}"
    except Exception:
        return f"127.0.0.1:{default_port}"


async def _start_ollama(key: str, endpoint: str = "", force: bool = False) -> tuple[bool, str]:
    cfg = load_config()
    base = endpoint or platforms.endpoints(cfg).get("ollama", "")
    healthy, _, _ = await platforms._probe_external(base, "/api/tags")
    if healthy and not force:
        return True, "Ollama 已在运行，跳过启动"
    if healthy and force:
        proc = PROCS.get(key)
        if proc and proc.poll() is None:
            return True, "Ollama 已在运行（工作台拉起的进程）"
        return False, (f"{base} 上已经有另一个 Ollama 在跑（多半是托盘里的系统版）。"
                       "请先退出它（托盘图标右键 Quit），再点一次“装到工作台目录”，这样才会用到 platforms\\ollama 的程序和模型")
    exe = portable_ollama(cfg) or detect("ollama")["path"]
    if not exe:
        return False, "没有找到 ollama 程序"
    models = ollama_models_dir(cfg)
    models.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "ollama.log", "a", encoding="utf-8")
    env = os.environ.copy()
    env["OLLAMA_HOST"] = _host_port(base)
    env["OLLAMA_MODELS"] = str(models)   # 让模型落在 platforms/ollama/models，而不是 ~/.ollama
    flags = CREATE_NO_WINDOW if IS_WINDOWS else 0
    PROC = subprocess.Popen([exe, "serve"], stdout=log, stderr=subprocess.STDOUT,
                            creationflags=flags, env=env)
    PROCS[key] = PROC
    for _ in range(20):
        await asyncio.sleep(1)
        healthy, _, _ = await platforms._probe_external(base, "/api/tags")
        if healthy:
            return True, f"Ollama 已启动（PID {PROC.pid}，模型目录 {models}）"
    return False, "Ollama 进程已启动，但端口还没响应，请查看 data/logs/ollama.log"


async def _deploy_ollama(key: str, endpoint: str = "", force: bool = False) -> tuple[bool, str, bool]:
    cfg = load_config()
    portable = portable_ollama(cfg)
    sys_exe = _system_ollama()
    skipped = bool(portable and not force) or bool(sys_exe and not force and not portable)
    if portable and not force:
        _set(key, step="跳过安装", msg=f"已使用工作台目录里的 Ollama：{portable}")
    elif sys_exe and not force:
        _set(key, step="跳过安装",
             msg=f"检测到系统安装的 Ollama（{sys_exe}），先用它；要统一到 platforms/ollama 请点“装到工作台目录”")
    else:
        _set(key, pct=8, step="安装", msg="开始安装便携版 Ollama 到 platforms/ollama")
        ok, msg = await _install_ollama(key, force=force)
        if not ok:
            return False, msg, False
    ok, msg = await _start_ollama(key, endpoint, force=force)
    if portable_ollama(cfg) and _has_models(system_ollama_models_dir()) and not _has_models(ollama_models_dir(cfg)):
        msg += "；系统目录里还有旧模型，可点“迁移旧模型”把 .ollama 的模型搬进来"
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


async def adopt_ollama_models() -> dict[str, Any]:
    """把系统版 Ollama 的模型（~/.ollama/models）搬到 platforms/ollama/models。

    同一个盘上挪动是改名，几乎瞬间完成；跨盘会自动退化成复制后删除。
    """
    cfg = load_config()
    src = system_ollama_models_dir()
    dst = ollama_models_dir(cfg)
    if not _has_models(src):
        return {"ok": False, "msg": f"{src} 里没有模型，不需要迁移"}
    if not portable_ollama(cfg):
        return {"ok": False, "msg": "请先点“装到工作台目录”把 Ollama 便携版装进 platforms/ollama，再迁移模型"}
    if _state("ollama").get("running"):
        return {"ok": False, "msg": "Ollama 正在部署，请稍后再迁移"}
    base = platforms.endpoints(cfg).get("ollama", "")
    proc = PROCS.get("ollama")
    ours = bool(proc and proc.poll() is None)
    healthy, _, _ = await platforms._probe_external(base, "/api/tags")
    if healthy and not ours:
        return {"ok": False, "msg": "本机 Ollama 服务正在运行（不是工作台拉起的），请先退出托盘里的 Ollama 再迁移"}
    if ours:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            pass
    moved = 0
    total = 0
    errors: list[str] = []
    for sub in ("blobs", "manifests"):
        s = src / sub
        if not s.exists():
            continue
        d = dst / sub
        d.mkdir(parents=True, exist_ok=True)
        for item in sorted(s.iterdir()):
            target = d / item.name
            if target.exists():
                continue
            try:
                size = item.stat().st_size if item.is_file() else 0
                shutil.move(str(item), str(target))
                moved += 1
                total += size
            except Exception as exc:
                errors.append(f"{item.name}: {exc}")
    for sub in ("blobs", "manifests"):
        s = src / sub
        try:
            if s.exists() and not any(s.iterdir()):
                s.rmdir()
        except Exception:
            pass
    restarted = ""
    if ours:
        ok, msg = await _start_ollama("ollama", base)
        restarted = f"；重启 Ollama：{msg}" if ok else f"；重启 Ollama 失败：{msg}"
    size_text = f"{total / 2**30:.1f} GB" if total >= 2**30 else f"{total / 2**20:.0f} MB"
    if errors:
        return {"ok": False, "msg": f"迁移了 {moved} 个文件（{size_text}），{len(errors)} 个失败：{errors[0]}",
                "moved": moved, "errors": errors[:5], "dst": str(dst)}
    return {"ok": True, "msg": f"已把系统目录的模型搬到 {dst}（{moved} 个文件，{size_text}）{restarted}",
            "moved": moved, "dst": str(dst), "restarted": bool(restarted)}


# ---------------------------------------------------------------- Ollama 拉取模型
PULL: dict[str, Any] = {"running": False, "tag": "", "pct": 0, "step": "", "msg": "尚未拉取",
                       "ok": None, "error": "", "started_at": 0, "finished_at": 0}


def pull_state() -> dict[str, Any]:
    item = dict(PULL)
    item["elapsed"] = round(time.time() - item["started_at"], 1) if item["running"] and item["started_at"] else 0
    return item


def _pull_set(**kw) -> None:
    PULL.update(kw)


async def ollama_pull(tag: str) -> dict[str, Any]:
    """用 Ollama 自己的 HTTP 接口拉模型，进度落在 PULL 状态里供控制台轮询。

    走 ``/api/pull`` 而不是命令行，是因为它能直接给出 ``completed/total`` 字节数，
    控制台可以显示百分比；pull 结束后模型就落在 OLLAMA_MODELS（platforms/ollama/models）。
    """
    cfg = load_config()
    base = platforms.endpoints(cfg).get("ollama", "")
    healthy, _, detail = await platforms._probe_external(base, "/api/tags")
    if not healthy:
        return {"ok": False, "msg": f"Ollama 服务没在运行（{base}）：请先在部署卡片点“启动”，再拉模型"}
    if PULL.get("running"):
        return {"ok": False, "msg": f"正在拉取 {PULL.get('tag') or '模型'}，请等这一轮结束"}
    _pull_set(running=True, tag=tag, pct=1, step="排队", msg=f"准备拉取 {tag}",
              ok=None, error="", started_at=time.time(), finished_at=0)
    asyncio.create_task(_pull_task(base, tag))
    return {"ok": True, "msg": f"开始拉取 {tag}；模型会落到 {ollama_models_dir(cfg)}"}


async def _pull_task(base: str, tag: str) -> None:
    from . import platform_models  # 拉完让模型列表缓存立刻失效
    try:
        _pull_set(pct=3, step="连接", msg=f"连接 {base} 拉取 {tag}")
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{base}/api/pull",
                                     json={"name": tag, "stream": True}) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise RuntimeError(f"Ollama 返回 {resp.status_code}：{body}")
                async for line in resp.aiter_lines():
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    status = str(payload.get("status") or "").strip()
                    total = int(payload.get("total") or 0)
                    done = int(payload.get("completed") or 0)
                    if payload.get("error"):
                        raise RuntimeError(str(payload["error"])[:300])
                    if total and done:
                        pct = 5 + round(min(done / total, 0.99) * 85, 1)
                        _pull_set(pct=pct, step="下载",
                                  msg=f"{status or '下载'} {done / 2**20:.0f}/{total / 2**20:.0f} MB")
                    elif status:
                        _pull_set(step="处理", msg=status[:160], pct=max(PULL.get("pct", 0), 5))
        platform_models.invalidate()
        _pull_set(running=False, ok=True, pct=100, step="完成",
                  msg=f"{tag} 已拉取完成，可在“模型”页切换使用", finished_at=time.time())
    except Exception as exc:
        _pull_set(running=False, ok=False, step="失败", error=str(exc)[:300],
                  msg=f"拉取 {tag} 失败：{str(exc)[:200]}", finished_at=time.time())


# ---------------------------------------------------------------- 卸载（删程序、保模型）
def _dir_bytes(path: Path) -> int:
    total = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except Exception:
                continue
    except Exception:
        pass
    return total


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _human(n: int) -> str:
    if n >= 2**30:
        return f"{n / 2**30:.2f} GB"
    if n >= 2**20:
        return f"{n / 2**20:.0f} MB"
    return f"{n / 2**10:.0f} KB"


async def _kill_ours(proc: subprocess.Popen | None, timeout: float = 15) -> bool:
    if not proc or proc.poll() is not None:
        return False
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            proc.terminate()
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


async def uninstall(key: str) -> dict[str, Any]:
    """卸载工作台自己装进 platforms/ 的东西，顺手关掉进程与端口。

    保留两类“使用者自己下的东西”：Ollama 的 models 目录、data\\installers 里的安装包。
    系统安装（LM Studio、系统版 Ollama）不归工作台管，直接拒绝并提示去系统里卸。
    """
    if key not in platforms.PLATFORMS:
        return {"ok": False, "msg": "未知平台"}
    if _state(key).get("running"):
        return {"ok": False, "msg": "这个平台正在部署，等它跑完再卸载"}
    if key == "ollama" and PULL.get("running"):
        return {"ok": False, "msg": f"正在拉取 {PULL.get('tag')}，等拉完再卸载"}

    cfg = load_config()
    root = _platforms_root(cfg)
    kept_models = ""
    targets: list[Path] = []
    freed = 0

    if key == "ollama":
        if not portable_ollama(cfg):
            return {"ok": False, "msg": "这台机子的 Ollama 装在系统目录（不是工作台装的），工作台没有可删的东西；"
                                        "要卸载请到 Windows“设置 → 应用”或托盘里退出后手动删除"}
        base = platforms.endpoints(cfg).get("ollama", "")
        proc = PROCS.get("ollama")
        ours = bool(proc and proc.poll() is None)
        healthy, _, _ = await platforms._probe_external(base, "/api/tags")
        if healthy and not ours:
            return {"ok": False, "msg": "Ollama 服务正在运行，但不是工作台拉起的（多半是托盘里的 Ollama）。"
                                        "请先在托盘右键 Quit，再点“卸载”"}
        stopped = await _kill_ours(proc) if ours else False
        d = ollama_dir(cfg)
        models = ollama_models_dir(cfg)
        kept_models = str(models)
        for child in sorted(d.iterdir()) if d.exists() else []:
            if child.name == "models":
                continue
            targets.append(child)
        # 下载缓存里那个便携包也清掉，省一份磁盘
        _, name = ollama_archive()
        cache = root / ".downloads" / name
        if cache.exists():
            targets.append(cache)
        freed = sum(_dir_bytes(p) for p in targets)
        for p in targets:
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        if d.exists() and not _has_models(models):
            shutil.rmtree(d, ignore_errors=True)
            kept_models = ""
    elif key == "llama.cpp":
        try:
            await llama.server.stop()
        except Exception:
            pass
        flags = CREATE_NO_WINDOW
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"],
                           capture_output=True, creationflags=flags)
        else:
            subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
        d = Path(str(cfg.get("llama_dir") or "")).expanduser()
        if not d.exists() or not _is_under(d, root):
            return {"ok": False, "msg": f"llama.cpp 不在工作台目录里（{d or '未配置'}），工作台没有可删的东西；请手动删除"}
        freed = _dir_bytes(d)
        shutil.rmtree(d, ignore_errors=True)
        kept_models = str(cfg.get("models_dir") or "")
    else:
        return {"ok": False, "msg": "LM Studio、vLLM、自定义平台都是系统安装或外部服务，工作台不接管卸载；"
                                    "请到各自目录/程序列表里手动卸载"}

    if PULL.get("tag") and key == "ollama":
        _pull_set(running=False, ok=None, pct=0, step="", msg="尚未拉取", tag="")
    _set(key, running=False, ok=None, skipped=False, pct=0, step="", msg="已卸载，可重新一键部署",
         error="", started_at=0, finished_at=time.time())
    from . import platform_models
    platform_models.invalidate()
    msg = f"已卸载 {key}，释放 {_human(freed)}；相关进程和端口已关闭"
    if kept_models:
        msg += f"；你的模型保留在 {kept_models}"
    msg += f"；{DATA_DIR / 'installers'} 里的安装包也保留着"
    return {"ok": True, "msg": msg, "freed": freed, "kept_models": kept_models}


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
            ok, msg, skipped = await _deploy_ollama(key, endpoint, force)
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
