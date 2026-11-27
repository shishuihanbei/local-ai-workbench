"""本地平台单平台一键部署：检测、跳过已安装、安装并启动。

四个引擎共用同一套流程和同一批目录（见 platform_store）：
参数层（下载到 platforms\\.downloads）→ 装到 platforms\\<引擎> → 启动 → 探测 → 记录状态。

llama.cpp 由工作台自己管理，装在 platforms/llama.cpp；Ollama 装成便携版；
LM Studio 用它的无界面版 llmster（zip 解压即用，模型也在工作台目录里）；
vLLM 在 platforms/vllm 建独立虚拟环境后 pip 安装（官方只支持 Linux，Windows 给 WSL2 命令）。
自定义平台只做连接测试。
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import httpx

from ..config import CREATE_NO_WINDOW, DATA_DIR, IS_WINDOWS, load_config
from ..db import fetch_all
from .. import ollama_tags
from . import hardware, installer, llama, platform_models, platform_store, platforms

STATE: dict[str, dict[str, Any]] = {}
log = logging.getLogger("workbench.platform_deploy")
PROCS: dict[str, subprocess.Popen] = {}
LOG_DIR = DATA_DIR / "logs"

# LM Studio 的无界面版：官方 zip 解压后自带 llmster / lms，模型和程序都能留在工作台目录
LLMSTER_VERSION = "0.0.27-1"
LLMSTER_BASE = "https://llmster.lmstudio.ai/download"
LMSTUDIO_PORT = 1234
VLLM_PORT = 8000


def _blank() -> dict[str, Any]:
    return {"running": False, "ok": None, "skipped": False, "pct": 0, "step": "",
            "msg": "尚未部署", "error": "", "started_at": 0, "finished_at": 0,
            "cancel": False, "cancelled": False}


class DeployCancelled(Exception):
    """用户点了“取消部署”。"""


def _state(key: str) -> dict[str, Any]:
    return STATE.setdefault(key, _blank())


def _set(key: str, **kw) -> None:
    _state(key).update(kw)


def get_state(key: str) -> dict[str, Any]:
    st = dict(_state(key))
    st.pop("task", None)
    st.pop("proc", None)
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


def request_cancel(key: str) -> dict[str, Any]:
    """让正在跑的部署尽快停下：下载在下一个分片停、子进程直接结束。

    已下载的 .part 和已解压的程序都不动，属于“暂停”而不是回滚。
    """
    st = _state(key)
    if not st.get("running"):
        return {"ok": False, "msg": "这个平台当前没有在部署", "state": get_state(key)}
    st["cancel"] = True
    _set(key, step="取消中", msg="正在停止部署，已下载的部分会保留")
    if key == "llama.cpp":
        installer.request_cancel()
    proc = st.get("proc")
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    return {"ok": True, "msg": "已请求取消，正在停止", "state": get_state(key)}


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
    """Ollama 的模型目录：统一放在 <models_dir>/ollama，不再跟程序目录走。"""
    env = os.getenv("WORKBENCH_OLLAMA_MODELS")
    if env:
        return Path(env).expanduser()
    return platform_store.models_dir(cfg or load_config(), "ollama")


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


# ---------------------------------------------------------------- LM Studio（无界面版 llmster）
def lmstudio_dir(cfg: dict[str, Any] | None = None) -> Path:
    return platform_store.target(cfg or load_config(), "lmstudio")


def lmstudio_home(cfg: dict[str, Any] | None = None) -> Path:
    """llmster 的“LM Studio 家目录”：程序、配置、缓存都落在这里，不碰 ~/.lmstudio。"""
    return lmstudio_dir(cfg) / "home"


def lmstudio_models_dir(cfg: dict[str, Any] | None = None) -> Path:
    """LM Studio 的模型目录：和 Ollama 一样收到 <models_dir>/lmstudio 下。"""
    return platform_store.models_dir(cfg or load_config(), "lmstudio")


def lmstudio_config_file(cfg: dict[str, Any] | None = None) -> Path:
    return lmstudio_home(cfg) / ".lmstudio" / "config.json"


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except Exception:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _is_dir_link(p: Path) -> bool:
    try:
        return p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)())
    except Exception:
        return False


def _drop_dir_link(p: Path) -> None:
    """只删链接本身，不碰链接指向的模型目录。"""
    try:
        if p.is_symlink():
            p.unlink()
        elif getattr(p, "is_junction", lambda: False)():
            p.rmdir()
    except Exception:
        pass


def _merge_tree(src: Path, dst: Path) -> bool:
    """把 src 合并进 dst；同名已存在就保留 dst，不覆盖用户文件。"""
    if not src.exists() or not src.is_dir() or _same_dir(src, dst):
        return False
    if _is_dir_link(src):
        _drop_dir_link(src)
        return False
    try:
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return True
        moved = False
        for item in list(src.iterdir()):
            target = dst / item.name
            if target.exists():
                if item.is_dir() and not _is_dir_link(item):
                    moved = _merge_tree(item, target) or moved
            else:
                shutil.move(str(item), str(target))
                moved = True
        try:
            src.rmdir()
        except OSError:
            pass
        return moved
    except Exception:
        log.exception("合并模型目录失败：%s -> %s", src, dst)
        return False


def ensure_lmstudio_models(cfg: dict[str, Any] | None = None, write_config: bool = True) -> Path:
    """把 LM Studio 的家目录模型路径收到 models/lmstudio，并写进它的 config.json。

    LM Studio 只认自己的 modelsDirectory 配置，不能直接吃平铺的 .gguf；
    统一后模型仍在 models 根下，只是多一层 lmstudio 子目录。
    """
    cfg = cfg or load_config()
    target = lmstudio_models_dir(cfg)
    target.mkdir(parents=True, exist_ok=True)
    # 老版本把模型放在 platforms/lmstudio/models 或 home/.lmstudio/models，先搬过来
    for src in (lmstudio_home(cfg) / ".lmstudio" / "models", lmstudio_dir(cfg) / "models"):
        if src.exists() and not _same_dir(src, target):
            _merge_tree(src, target)
    if write_config:
        conf = lmstudio_config_file(cfg)
        data: dict[str, Any] = {}
        try:
            if conf.is_file():
                raw = json.loads(conf.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
        except Exception:
            data = {}
        data["modelsDirectory"] = str(target)
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _migrate_ollama_models(cfg: dict[str, Any]) -> Path:
    """老版本的 platforms/ollama/models 搬到 models/ollama；同盘改名，很快。"""
    target = ollama_models_dir(cfg)
    old = ollama_dir(cfg) / "models"
    if old.exists() and not _same_dir(old, target):
        _merge_tree(old, target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_model_layout(cfg: dict[str, Any] | None = None) -> None:
    """启动时调用一次：把 Ollama / LM Studio 的模型都收进 models 根目录。"""
    cfg = cfg or load_config()
    try:
        _migrate_ollama_models(cfg)
    except Exception:
        log.exception("迁移 Ollama 模型目录失败")
    try:
        if lmstudio_dir(cfg).exists() or (lmstudio_home(cfg) / ".lmstudio").exists():
            ensure_lmstudio_models(cfg)
    except Exception:
        log.exception("整理 LM Studio 模型目录失败")


LMS_NAMES = (
    "home/.lmstudio/bin/lms.exe", "home/.lmstudio/bin/lms",
    "bin/lms.exe", "bin/lms", "lms.exe", "lms",
)


def managed_lms(cfg: dict[str, Any] | None = None) -> str:
    root = lmstudio_dir(cfg)
    for rel in LMS_NAMES:
        p = root / rel
        if p.is_file():
            return str(p)
    return ""


def managed_llmster(cfg: dict[str, Any] | None = None) -> str:
    root = lmstudio_dir(cfg)
    for rel in ("llmster.exe", "llmster", "home/.lmstudio/bin/llmster.exe", "home/.lmstudio/bin/llmster"):
        p = root / rel
        if p.is_file():
            return str(p)
    return ""


def lmstudio_archive(version: str = LLMSTER_VERSION) -> tuple[str, str, str]:
    """llmster 官方 zip：返回 (下载地址, 文件名, sha512 地址)。"""
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    name = f"{version}-win32-{arch}.full.zip"
    url = f"{LLMSTER_BASE}/{name}"
    return url, name, url + ".sha512"


# ---------------------------------------------------------------- vLLM（独立 venv）
def vllm_dir(cfg: dict[str, Any] | None = None) -> Path:
    return platform_store.target(cfg or load_config(), "vllm")


def vllm_python(cfg: dict[str, Any] | None = None) -> str:
    root = vllm_dir(cfg) / ".venv"
    for rel in ("Scripts/python.exe", "bin/python"):
        p = root / rel
        if p.is_file():
            return str(p)
    return ""


def vllm_bin(cfg: dict[str, Any] | None = None) -> str:
    root = vllm_dir(cfg) / ".venv"
    for rel in ("Scripts/vllm.exe", "bin/vllm"):
        p = root / rel
        if p.is_file():
            return str(p)
    return ""


def vllm_managed(cfg: dict[str, Any] | None = None) -> bool:
    """工作台自己的 venv 里装上了 vllm 才算“托管安装”。"""
    py = vllm_python(cfg)
    if not py:
        return False
    exe = vllm_bin(cfg)
    if exe:
        return True
    try:
        out = subprocess.run([py, "-c", "import vllm; print(vllm.__version__)"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=15, creationflags=CREATE_NO_WINDOW)
        return out.returncode == 0
    except Exception:
        return False


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
    if not archive.exists() or archive.stat().st_size == 0:
        raise RuntimeError(f"安装包不存在或为空：{archive}")
    tmp = platform_store.workbench_tmp(load_config(), "extract")
    try:
        if archive.name.endswith(".tgz") or archive.name.endswith(".tar.gz"):
            try:
                with tarfile.open(archive) as tf:
                    for member in tf.getmembers():
                        parts = Path(member.name).parts
                        if Path(member.name).is_absolute() or ".." in parts:
                            raise RuntimeError("安装包包含不安全路径")
                    tf.extractall(tmp, filter="data")
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"安装包解不开：{installer.head_hint(archive)}，"
                    f"文件 {archive.stat().st_size/2**20:.1f} MB") from exc
        else:
            hint = installer.head_hint(archive)
            size = archive.stat().st_size / 2**20
            if not installer.looks_like_zip(archive):
                # 网页/错误页当压缩包下回来的常见情形：删掉缓存，下次重下
                try:
                    archive.unlink()
                except Exception:
                    pass
                raise RuntimeError(
                    f"下载回来的不是 zip：{hint}，文件 {size:.1f} MB，已删除坏缓存，请重试")
            try:
                with zipfile.ZipFile(archive) as zf:
                    bad = zf.testzip()
                    if bad:
                        raise RuntimeError(f"安装包压缩校验失败：{bad}")
                    for name in zf.namelist():
                        parts = Path(name).parts
                        if Path(name).is_absolute() or ".." in parts:
                            raise RuntimeError("安装包包含不安全路径")
                    zf.extractall(tmp)
            except RuntimeError:
                raise
            except Exception as exc:
                try:
                    archive.unlink()
                except Exception:
                    pass
                raise RuntimeError(
                    f"安装包解不开（{hint}，文件 {size:.1f} MB），已删除坏缓存，请重试") from exc
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
        cfg = load_config()
        managed = vllm_managed(cfg)
        exe = vllm_bin(cfg)
        path = exe or ("platforms\\vllm\\.venv" if managed else "")
        if not path:
            path = _which("vllm")
        spec = bool(importlib.util.find_spec("vllm"))
        return {"installed": bool(path or spec), "path": path or ("python 包" if spec else ""),
                "managed": managed, "venv": str(vllm_dir(cfg) / ".venv"),
                "version": _version([path, "--version"]) if path else "",
                "installable": platform.system().lower() == "linux"}
    if key == "lmstudio":
        cfg = load_config()
        lms = managed_lms(cfg)
        llmster = managed_llmster(cfg)
        sys_path = _which("lms") or _exists(
            r"%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe",
            r"%LOCALAPPDATA%\LM Studio\LM Studio.exe",
            r"%ProgramFiles%\LM Studio\LM Studio.exe",
            "/Applications/LM Studio.app",
        )
        path = lms or llmster or sys_path
        return {"installed": bool(path), "path": path, "managed": bool(lms or llmster),
                "lms": lms, "llmster": llmster,
                "models_path": str(platform_store.models_dir(cfg, "lmstudio")),
                "version": "", "installable": IS_WINDOWS}
    return {"installed": None, "path": "", "version": "", "installable": False}


def engine_usage(key: str, item: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """部署好之后到底怎么用：地址、模型、调用示例、接入步骤。

    这里只描述“已经装好/服务健康”之后的事，不替用户决定装哪个引擎。
    """
    models = [str(m) for m in (item.get("models") or []) if str(m)]
    if key == "llama.cpp":
        base = str(cfg.get("upstream_base") or "").rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        port = base.rsplit(":", 1)[-1] if ":" in base else "8080"
    else:
        base = str(item.get("base_url") or "").rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        port = base.rsplit(":", 1)[-1] if ":" in base else ""
    api = f"{base}/v1" if base else ""
    model = models[0] if models else ""
    steps = {
        "llama.cpp": [
            "本卡显示“已运行/已连接”后，到「模型」页点“加载”切换要用的 GGUF 模型",
            "用户端模型下拉会自动多出这个模型，选中即可对话",
            f"外部程序调用：{api}/chat/completions，Key 任意（本机不校验）",
        ],
        "ollama": [
            "本卡点“启动”，等状态变成“已连接”",
            "拉模型：在「模型」页点“用 Ollama 拉取”，或命令行 ollama pull qwen2.5:7b（模型落在 models\\ollama）",
            "用户端模型下拉自动出现该模型；也可以直接调下面的接口地址",
        ],
        "lmstudio": [
            "本卡“一键部署”装的是 LM Studio 的无界面版 llmster：程序、模型都在 platforms\\lmstudio，不需要打开桌面客户端",
            "拉模型：lms get qwen2.5-7b-instruct（或先装桌面版在图形界面里下载，工作台能识别）",
            "本卡点“启动”后，用户端模型下拉自动出现该模型",
        ],
        "vllm": [
            "Linux 上本卡会建 platforms\\vllm\\.venv 并 pip 安装 vLLM；Windows 请照本卡说明用 WSL2",
            "先让「模型」页下载好一个 Hugging Face 仓库模型，本卡点“启动”会用它起服务",
            "服务起来后用户端模型下拉自动出现该模型；接口是 OpenAI 兼容的 /v1",
        ],
    }.get(key, [])
    curl = ""
    if api:
        curl = (f'curl {api}/chat/completions -H "Content-Type: application/json" '
                f'-d \'{{"model":"{model or "你的模型"}","messages":[{{"role":"user","content":"你好"}}]}}\'')
    return {
        "api_base": api,
        "chat_url": f"{api}/chat/completions" if api else "",
        "models": models[:8],
        "sample_model": model,
        "curl": curl,
        "steps": steps,
        # 前端模型下拉是自动接入的：只要平台健康，platform_models 就会把模型列出来
        "frontend_auto": True,
        "frontend_ready": bool(item.get("healthy")) and bool(models),
        "frontend_count": len(models),
        "port": port,
    }


def enrich(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把安装状态、按钮文案、进度和“接入与使用”补到平台卡片上。"""
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
        item["can_manage"] = key in ("ollama", "lmstudio", "vllm") and bool(item["installed"]) and not item["managed"]
        if key == "llama.cpp":
            item["models_path"] = str(cfg.get("models_dir") or "")
            item["target_path"] = str(platform_store.target(cfg, key))
        if key == "ollama":
            item["target_path"] = str(ollama_dir(cfg))
        if key in ("lmstudio", "vllm"):
            item["target_path"] = str(platform_store.target(cfg, key))
        item["usage"] = engine_usage(key, item, cfg)
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


def _run(key: str, cmd: list[str], timeout: int = 1800, env: dict | None = None,
         idle_label: str = "正在执行安装命令") -> None:
    """在线程里跑安装命令，避免卡住事件循环；可被“取消部署”打断。"""
    _set(key, msg=idle_label)
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                env=env, creationflags=CREATE_NO_WINDOW)
        _set(key, proc=proc)
        deadline = time.time() + timeout
        while proc.poll() is None:
            if _state(key).get("cancel"):
                try:
                    proc.kill()
                except Exception:
                    pass
                raise DeployCancelled("部署已取消")
            if time.time() > deadline:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise RuntimeError(f"安装超时（{timeout // 60} 分钟）")
            time.sleep(0.4)
        try:
            out = (proc.stdout.read() if proc.stdout else "") or ""
        except Exception:
            out = ""
        if _state(key).get("cancel"):
            raise DeployCancelled("部署已取消")
        if proc.returncode != 0:
            tail = _tail(out)
            raise RuntimeError(f"安装命令失败（退出码 {proc.returncode}）：{tail or '没有输出'}")
        tail = _tail(out)
        if tail:
            _set(key, msg=tail)
    finally:
        _set(key, proc=None)


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
    await installer._download(url, dest, on_progress=progress,
                              should_cancel=lambda: bool(_state(key).get("cancel")))


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
    cache = platform_store.download_dir(cfg, "ollama") / name
    legacy = _platforms_root(cfg) / ".downloads" / name   # 老版本缓存位置
    if legacy.exists() and legacy.stat().st_size > 0 and not cache.exists():
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(cache))
        except Exception:
            cache = legacy
    local_arc = ""
    for suffix in (".zip", ".tgz"):
        local_arc = local_arc or _local_installer("ollama", suffix)
    try:
        if local_arc and not (cache.exists() and cache.stat().st_size > 0):
            archive = Path(local_arc)
            _set(key, pct=60, step="本地包", msg=f"使用本地便携包 {archive.name}")
        else:
            archive = cache
            if force:
                cache.unlink(missing_ok=True)
                cache.with_name(cache.name + ".part").unlink(missing_ok=True)
            if cache.exists() and cache.stat().st_size > 0 and not installer.looks_like_archive(cache):
                # 上次下回来的不是 zip（网页/错误页），直接丢掉重下
                cache.unlink(missing_ok=True)
            if cache.exists() and cache.stat().st_size > 0:
                _set(key, pct=60, step="本地缓存", msg=f"使用已下载的 {name}")
            else:
                _set(key, pct=8, step="下载", msg=f"下载便携版 {name}")
                await _download_file(key, url, cache)
        _set(key, pct=70, step="解压", msg=f"解压到 {target}")
        await asyncio.to_thread(_extract_archive, archive, target)
    except Exception as exc:
        if isinstance(exc, (DeployCancelled, installer.DownloadCancelled)):
            raise
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
    models = _migrate_ollama_models(cfg)
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
        return True, "Ollama 已在运行"
    if healthy and force:
        proc = PROCS.get(key)
        if proc and proc.poll() is None:
            return True, "Ollama 已在运行（工作台拉起的进程）"
        return False, (f"{base} 上已经有另一个 Ollama 在跑（多半是托盘里的系统版）。"
                       "请先退出它（托盘图标右键 Quit），再点一次“装到工作台目录”，这样才会用到 platforms\\ollama 的程序和模型")
    exe = portable_ollama(cfg) or detect("ollama")["path"]
    if not exe:
        return False, "没有找到 ollama 程序"
    gpid = _managed_pids(key)
    if gpid:
        return False, (f"Ollama 进程已经在跑（PID {gpid[0]}），只是端口暂时没响应；"
                       "不要重复启动。先看 data/logs/ollama.log，或点“停止”后再启动")
    models = _migrate_ollama_models(cfg)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "ollama.log", "a", encoding="utf-8")
    env = platform_store.child_env(cfg)
    env["OLLAMA_HOST"] = _host_port(base)
    env["OLLAMA_MODELS"] = str(models)   # 统一落在 models/ollama，而不是 ~/.ollama
    flags = CREATE_NO_WINDOW if IS_WINDOWS else 0
    PROC = subprocess.Popen([exe, "serve"], stdout=log, stderr=subprocess.STDOUT,
                            creationflags=flags, env=env)
    PROCS[key] = PROC
    for _ in range(30):
        await asyncio.sleep(0.4)
        healthy, _, _ = await platforms._probe_external(base, "/api/tags", timeout=0.5)
        if healthy:
            return True, f"Ollama 已启动（PID {PROC.pid}，模型目录 {models}）"
    return False, "Ollama 进程已启动，但端口还没响应，请查看 data/logs/ollama.log"


def _managed_pids(key: str) -> list[int]:
    """当前在跑的、属于工作台目录的进程。后端重启后 PROCS 会丢，按 exe 路径认回来。"""
    proc = PROCS.get(key)
    if proc and proc.poll() is None:
        return [int(proc.pid)]
    info = detect(key)
    exe = str(info.get("path") or "").lower()
    if not exe:
        return []
    pids: list[int] = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "exe"]):
            if str(p.info.get("exe") or "").lower() == exe:
                pids.append(int(p.info["pid"]))
    except Exception:
        pass
    return pids


async def start(key: str, endpoint: str = "") -> dict:
    """已安装平台的“启动”：只拉起服务，不重新走安装、不打印跳过安装的日志。"""
    if key not in platforms.PLATFORMS:
        return {"ok": False, "msg": "未知平台"}
    if _state(key).get("running"):
        return {"ok": False, "msg": "这个平台正在启动，请稍等"}
    endpoint = str(endpoint or "").strip()[:300].rstrip("/")
    if endpoint.endswith("/v1"):
        endpoint = endpoint[:-3]
    info = detect(key)
    if not info.get("installed"):
        return {"ok": False, "msg": "还没有安装，请先点“一键部署”"}
    name = platforms.PLATFORMS[key]["name"]
    STATE[key] = {**_blank(), "running": True, "pct": 5, "step": "启动",
                  "msg": f"正在启动 {name}", "started_at": time.time(), "task": asyncio.current_task()}
    try:
        if key == "llama.cpp":
            srv = await llama.server.status()
            if srv.get("healthy"):
                ok, msg = True, "llama.cpp 已在运行"
            else:
                row = await _pick_local_model(load_config())
                if not row:
                    ok, msg = False, "还没有可用的 GGUF 模型，请先到「模型」页下载"
                else:
                    _set(key, pct=35, step="加载模型", msg=f"正在加载 {row['key']}")
                    ok, msg = await llama.server.start(row["key"])
        elif key == "ollama":
            ok, msg = await _start_ollama(key, endpoint)
        elif key == "lmstudio":
            ok, msg = await _start_lmstudio(key, endpoint)
        elif key == "vllm":
            ok, msg = await _start_vllm(key, endpoint)
        else:
            ok, msg = False, "这个平台只支持测试连接"
        _set(key, running=False, ok=ok, skipped=False,
             pct=100 if ok else get_state(key).get("pct", 5), step="运行中" if ok else "启动失败",
             msg=msg, error="" if ok else msg, finished_at=time.time())
        if ok:
            try:
                platform_models.invalidate()
            except Exception:
                pass
        return {"ok": ok, "msg": msg, "state": get_state(key)}
    except Exception as exc:
        _set(key, running=False, ok=False, step="启动失败", msg=f"启动失败：{exc}",
             error=str(exc), finished_at=time.time())
        return {"ok": False, "msg": str(exc), "state": get_state(key)}


async def stop(key: str, endpoint: str = "") -> dict:
    """停掉工作台自己拉起的进程。系统/外部启动的服务不动，避免误杀用户的东西。"""
    if key == "llama.cpp":
        await llama.server.stop()
        platform_models.invalidate()
        return {"ok": True, "msg": "llama.cpp 已停止"}
    pids = _managed_pids(key)
    if not pids:
        return {"ok": False, "msg": "这个服务不是工作台启动的，请到对应软件的托盘/服务里退出"}
    try:
        for pid in pids:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            else:
                os.kill(pid, 15)
    except Exception as exc:
        return {"ok": False, "msg": f"停止失败：{exc}"}
    PROCS.pop(key, None)
    _set(key, running=False, ok=True, skipped=False, pct=0, step="已停止",
         msg="已停止", error="", finished_at=time.time())
    platform_models.invalidate()
    return {"ok": True, "msg": "已停止"}


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


async def _verify_sha512(key: str, archive: Path, checksum_url: str) -> str:
    """尽量校验官方 sha512；拿不到校验值就跳过，不阻塞安装。"""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(checksum_url)
        expect = (resp.text or "").strip().split()[0].lower()
        if len(expect) != 128:
            return ""
        h = hashlib.sha512()
        with open(archive, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        got = h.hexdigest()
        if got != expect:
            archive.unlink(missing_ok=True)
            raise RuntimeError("安装包 sha512 校验不通过，已删除，请重试")
        _set(key, msg="sha512 校验通过")
        return got
    except RuntimeError:
        raise
    except Exception:
        return ""


async def _install_lmstudio(key: str, force: bool = False) -> tuple[bool, str, bool]:
    """把 LM Studio 的无界面版（llmster）装进 platforms\\lmstudio，和 Ollama 一样“解压即用”。

    官方 zip 里带 llmster.exe，第一次跑 bootstrap 时把它的家目录指到
    platforms\\lmstudio\\home，于是程序、模型、缓存都留在工作台目录里，
    不写 %LOCALAPPDATA% 也不写 ~\\.lmstudio。
    """
    cfg = load_config()
    lms = managed_lms(cfg)
    if lms and not force:
        _set(key, step="跳过安装", msg=f"已使用工作台目录里的 LM Studio 无界面版：{lms}")
        return True, "LM Studio 无界面版已就位", True
    if not IS_WINDOWS:
        info = detect(key)
        if info["installed"]:
            _set(key, step="跳过安装", msg=f"本机已有 LM Studio：{info['path']}")
            return True, "本机已有 LM Studio，跳过安装", True
        return False, "LM Studio 无界面版的一键安装目前只做 Windows；macOS/Linux 请按官网文档装好后回来填地址", False
    url, name, sha_url = lmstudio_archive()
    target = lmstudio_dir(cfg)
    archive = platform_store.download_dir(cfg, "lmstudio") / name
    if force:
        archive.unlink(missing_ok=True)
        archive.with_name(archive.name + ".part").unlink(missing_ok=True)
    if not (archive.exists() and archive.stat().st_size > 0):
        _set(key, pct=6, step="下载", msg=f"下载 LM Studio 无界面版 {name}")
        await _download_file(key, url, archive)
        await _verify_sha512(key, archive, sha_url)
    _set(key, pct=58, step="解压", msg=f"解压到 {target}")
    await asyncio.to_thread(_extract_archive, archive, target)
    llmster = target / "llmster.exe"
    if not llmster.is_file():
        found = sorted(target.rglob("llmster.exe"))
        llmster = found[0] if found else llmster
    if not llmster.is_file():
        return False, f"解压完成但没找到 llmster，请检查 {target} 里的包结构", False
    home = lmstudio_home(cfg)
    home.mkdir(parents=True, exist_ok=True)
    _set(key, pct=74, step="安装", msg=f"初始化 LM Studio 无界面版（家目录 {home}）")
    env = platform_store.child_env(cfg, {"LMS_NO_MODIFY_PATH": "1", "LMS_BOOTSTRAP_INSTALL_SH": "1"},
                                   home=home)
    await asyncio.to_thread(_run, key, [str(llmster), "bootstrap"], 1500, env)
    # 让 LM Studio 的模型目录收到 models/lmstudio，不再跟着 home 散落
    try:
        ensure_lmstudio_models(cfg)
    except Exception:
        log.exception("初始化 LM Studio 模型目录失败")
    lms = managed_lms(cfg)
    if not lms:
        return False, f"初始化完成但没在 {target} 里找到 lms，请查 data\\logs 或点“查看日志”", False
    _set(key, pct=92, step="安装", msg=f"lms：{lms}")
    return True, f"LM Studio 无界面版已装到 {target}（程序、模型、缓存都在这里）", False


async def _start_lmstudio(key: str, endpoint: str = "", force: bool = False) -> tuple[bool, str]:
    cfg = load_config()
    base = endpoint or platforms.endpoints(cfg).get("lmstudio", "")
    healthy, models, _ = await platforms._probe_external(base, "/v1/models")
    if healthy and not force:
        return True, f"LM Studio 服务已在运行（{len(models)} 个模型）" if models else "LM Studio 服务已在运行（还没加载模型）"
    info = detect(key)
    lms = str(info.get("lms") or "")
    llmster = str(info.get("llmster") or "")
    if not lms and not llmster:
        if info.get("installed"):
            return False, ("检测到系统安装的 LM Studio 桌面版：请在 Developer 页开启 Local Server（端口 1234）后回来点“更新”；"
                           "想把程序收进工作台目录，点“装到工作台目录”")
        return False, "没有找到 LM Studio，请先点“一键部署”"
    port = _host_port(base, LMSTUDIO_PORT).rsplit(":", 1)[-1]
    if info.get("managed"):
        try:
            ensure_lmstudio_models(cfg)
        except Exception:
            log.exception("写入 LM Studio 模型目录配置失败")
    env = platform_store.child_env(cfg, home=(lmstudio_home(cfg) if info.get("managed") else None))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "lmstudio.log", "a", encoding="utf-8")
    flags = CREATE_NO_WINDOW if IS_WINDOWS else 0
    cmd = [lms, "server", "start", "--port", port] if lms else [llmster, "serve", "--port", port]
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=flags, env=env, cwd=str(lmstudio_dir(cfg)))
    PROCS[key] = proc
    for _ in range(40):
        await asyncio.sleep(1)
        healthy, models, _ = await platforms._probe_external(base, "/v1/models")
        if healthy:
            extra = f"，{len(models)} 个模型" if models else "，还没有模型：用 lms get 拉一个"
            return True, f"LM Studio 服务已启动（PID {proc.pid}{extra}）"
        if proc.poll() is not None:
            break
    if proc.poll() is not None:
        if proc.returncode in (-1073741795, 3221225501):
            return False, ("LM Studio 0.0.27 的 lms 在这台 CPU 上无法运行："
                           "启动即非法指令退出（0xC000001D），说明 CPU 缺少 AVX2。"
                           "llmster 守护进程能装，但它不提供 1234 端口的 OpenAI 服务；"
                           "请换支持 AVX2 的 CPU，或用支持老 CPU 的旧版 LM Studio 桌面版")
        return False, "LM Studio 服务进程退出了，详见 data\\logs\\lmstudio.log（多半是缺模型、端口被占或初始化没完成）"
    return False, "LM Studio 进程已启动，但端口还没响应，详见 data\\logs\\lmstudio.log"


async def _deploy_lmstudio(key: str, endpoint: str = "", force: bool = False) -> tuple[bool, str, bool]:
    ok, msg, skipped = await _install_lmstudio(key, force=force)
    if not ok:
        return False, msg, skipped
    ok, msg2 = await _start_lmstudio(key, endpoint, force=force)
    return ok, msg2, skipped


def vllm_model_arg(cfg: dict) -> tuple[str, str]:
    """给 vllm serve 挑一个已下载的 Hugging Face 仓库（要有 config.json）。"""
    models_dir = Path(str(cfg.get("models_dir") or "")).expanduser()
    if not models_dir.exists():
        return "", ""
    for d in sorted(models_dir.iterdir()):
        try:
            if d.is_dir() and not d.name.startswith(".") and (d / "config.json").is_file():
                return d.name, str(d)
        except Exception:
            continue
    return "", ""


async def _install_vllm(key: str, force: bool = False) -> tuple[bool, str, bool]:
    """在 platforms\\vllm\\.venv 里装 vLLM：独立虚拟环境，不动工作台自己的依赖。"""
    cfg = load_config()
    if platform.system().lower() != "linux":
        return False, ("vLLM 官方只发 Linux 包，Windows 本机装不了（官方文档明确写了 not support Windows natively）。"
                       "三条可行路线：① WSL2：sudo apt install python3-venv，python3 -m venv ~/vllm，"
                       "~/vllm/bin/pip install vllm，~/vllm/bin/vllm serve 模型名 --port 8000；"
                       "② 用 Docker 的 vllm/vllm-openai 镜像（-p 8000:8000）；"
                       "③ 社区 Windows 轮子 SystemPanic/vllm-windows。"
                       "服务起来后把本卡地址改成 http://IP:8000 即可"), False
    if vllm_managed(cfg) and not force:
        _set(key, step="跳过安装", msg=f"已使用工作台目录里的 vLLM：{vllm_dir(cfg)}")
        return True, "vLLM 已装在 platforms\\vllm", True
    venv = vllm_dir(cfg) / ".venv"
    env = platform_store.child_env(cfg)
    env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    _set(key, pct=6, step="安装", msg=f"创建独立虚拟环境 {venv}")
    venv.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_run, key, [sys.executable, "-m", "venv", str(venv)], 600, env)
    py = vllm_python(cfg)
    if not py:
        return False, f"虚拟环境没建起来：{venv}", False
    _set(key, pct=18, step="安装", msg="pip 安装 vLLM（首次要下几 GB，慢慢等）")
    await asyncio.to_thread(_run, key, [py, "-m", "pip", "install", "-U", "pip"], 600, env)
    await asyncio.to_thread(_run, key, [py, "-m", "pip", "install", "-U", "vllm"], 3600, env)
    if not vllm_managed(cfg):
        return False, "pip 跑完了但 import vllm 失败：先点“网络诊断”确认 PyPI 镜像可用，再看 data\\logs", False
    return True, f"vLLM 已装到 {vllm_dir(cfg)}（独立 venv，不影响工作台依赖）", False


async def _start_vllm(key: str, endpoint: str = "", force: bool = False) -> tuple[bool, str]:
    cfg = load_config()
    base = endpoint or platforms.endpoints(cfg).get("vllm", "")
    healthy, models, _ = await platforms._probe_external(base, "/v1/models")
    if healthy and not force:
        return True, f"vLLM 服务已在运行（{len(models)} 个模型）"
    py = vllm_python(cfg)
    if not py or not vllm_managed(cfg):
        return False, "vLLM 还没装好，请先点“一键部署”（仅 Linux）"
    name, path = vllm_model_arg(cfg)
    if not path:
        return False, "vLLM 要指定一个 Hugging Face 仓库模型：先在「模型」页下载一个带 config.json 的仓库，再回来启动"
    hostport = _host_port(base, VLLM_PORT)
    host, port = hostport.rsplit(":", 1)
    env = platform_store.child_env(cfg)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / "vllm.log", "a", encoding="utf-8")
    exe = vllm_bin(cfg)
    cmd = ([exe, "serve", path, "--served-model-name", name, "--host", host, "--port", port]
           if exe else [py, "-m", "vllm.entrypoints.openai.api_server",
                        "--model", path, "--served-model-name", name, "--host", host, "--port", port])
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=0, env=env, cwd=str(vllm_dir(cfg)))
    PROCS[key] = proc
    for _ in range(60):
        await asyncio.sleep(1)
        healthy, models, _ = await platforms._probe_external(base, "/v1/models")
        if healthy:
            return True, f"vLLM 已启动（PID {proc.pid}，模型 {name}，{len(models)} 个可调用）"
        if proc.poll() is not None:
            break
    if proc.poll() is not None:
        return False, "vLLM 进程退出了，详见 data\\logs\\vllm.log（显存不足或模型不支持最常见）"
    return False, "vLLM 进程在跑，但 60 秒内端口没响应：大模型加载慢，可稍后点“更新”"


async def _deploy_vllm(key: str, endpoint: str = "", force: bool = False) -> tuple[bool, str, bool]:
    ok, msg, skipped = await _install_vllm(key, force=force)
    if not ok:
        return False, msg, skipped
    name, _ = vllm_model_arg(load_config())
    if not name:
        return True, "vLLM 已装好；还没有可用的 Hugging Face 仓库模型，先在「模型」页下载再点“启动”", skipped
    ok, msg2 = await _start_vllm(key, endpoint, force=force)
    return ok, msg2, skipped


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
        if result.get("cancelled"):
            raise DeployCancelled(result.get("msg") or "部署已取消")
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
# 一次只跑一个 pull；每个 tag 的进度单独记，页面刷新或进程重启后还能看到
# “已拉取 / 拉取中 / 已中断”，中断后再点同一个 tag 会从 Ollama 的 partial blob 续传。
PULL_FIELDS: dict[str, Any] = {
    "running": False, "tag": "", "pct": 0, "step": "", "msg": "尚未拉取",
    "ok": None, "error": "", "started_at": 0, "finished_at": 0,
    "updated_at": 0, "digest": "", "bytes": 0, "total": 0, "resumable": False,
}
PULL: dict[str, Any] = dict(PULL_FIELDS)
PULLS: dict[str, dict[str, Any]] = {}
_PULLS_LOADED = False
_PULL_SAVED_AT = 0.0
_PULL_FILE = DATA_DIR / "ollama_pulls.json"


def _pull_path() -> Path:
    return _PULL_FILE


def _load_pulls() -> None:
    global _PULLS_LOADED
    if _PULLS_LOADED:
        return
    _PULLS_LOADED = True
    try:
        raw = json.loads(_pull_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key, item in raw.items():
                if not isinstance(item, dict):
                    continue
                state = dict(PULL_FIELDS)
                state.update(item)
                state["tag"] = state.get("tag") or key
                # 进程重启时上一轮 HTTP 流已经断了，不能一直标“拉取中”
                if state.get("running"):
                    state["running"] = False
                    state["ok"] = False
                    state["step"] = "已中断"
                    state["resumable"] = True
                    state["msg"] = (state.get("msg") or "上次拉取没有完成")
                    if "中断" not in state["msg"]:
                        state["msg"] += "（已中断，可继续拉取）"
                PULLS[str(key)] = state
    except Exception:
        PULLS.clear()


def _save_pulls(force: bool = False) -> None:
    global _PULL_SAVED_AT
    now = time.time()
    if not force and now - _PULL_SAVED_AT < 1.0:
        return
    _PULL_SAVED_AT = now
    try:
        path = _pull_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(PULLS, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _digest_from_status(text: str) -> str:
    match = re.search(r"(?:pulling|verifying|writing)\s+([0-9a-fA-F]{8,})", text or "")
    return match.group(1).lower() if match else ""


def _partial_bytes(digest: str = "") -> int:
    """Ollama 下载中断后会留 ``sha256-<digest>-partial``，下次 pull 会复用它。"""
    try:
        cfg = load_config()
        blobs = Path(ollama_models_dir(cfg)) / "blobs"
        if digest:
            paths = list(blobs.glob(f"sha256-{digest}*-partial"))
        else:
            paths = [p for p in blobs.glob("*-partial") if p.is_file()]
        sizes = [p.stat().st_size for p in paths if p.is_file()]
        return max(sizes) if sizes else 0
    except Exception:
        return 0


def partial_state() -> dict[str, Any]:
    """控制台展示：即使没有 tag 记录，也能发现上次残留的未完成分片。"""
    load_config()
    _load_pulls()
    paths = []
    try:
        blobs = Path(ollama_models_dir(load_config())) / "blobs"
        for p in blobs.glob("*-partial*"):
            if not p.is_file() or p.stat().st_size <= 1024:
                continue
            # Ollama 0.40 会分多段写 -partial-0/-partial-1；模型拉完后完整 blob
            # 已经落盘，这些残片只是历史垃圾，不能再提示“未完成/可续传”。
            if (blobs / p.name.split("-partial")[0]).is_file():
                continue
            paths.append(p)
    except Exception:
        paths = []
    total = sum(p.stat().st_size for p in paths)
    return {"bytes": total, "count": len(paths),
            "msg": (f"有 {total / 2**20:.0f} MB 未完成分片，继续同一个 tag 会断点续传"
                    if total else "")}


def pull_state(tag: str | None = None) -> dict[str, Any]:
    _load_pulls()
    if tag:
        key = ollama_tags.tag_key(tag)
        item = dict(PULL_FIELDS)
        item.update(PULLS.get(key) or {})
        item["tag"] = tag
        # 全局正在跑同一个 tag 时，以内存里的实时进度为准
        if PULL.get("running") and ollama_tags.tag_key(PULL.get("tag") or "") == key:
            item.update(PULL)
        if item.get("running") and not PULL.get("running"):
            item["running"] = False
            item["step"] = item.get("step") or "已中断"
        item["elapsed"] = round(time.time() - item["started_at"], 1) if item["running"] and item["started_at"] else 0
        if not item.get("partial_bytes") and item.get("digest"):
            item["partial_bytes"] = _partial_bytes(item["digest"])
        else:
            item["partial_bytes"] = int(item.get("partial_bytes") or 0)
        return item
    item = dict(PULL)
    item["elapsed"] = round(time.time() - item["started_at"], 1) if item["running"] and item["started_at"] else 0
    return item


def _pull_set(tag: str = "", **kw) -> None:
    PULL.update({k: v for k, v in kw.items() if k != "tag"})
    if tag:
        PULL["tag"] = tag
        key = ollama_tags.tag_key(tag)
        item = PULLS.setdefault(key, dict(PULL_FIELDS))
        item.update(kw)
        item["tag"] = tag
        item["updated_at"] = time.time()
        _save_pulls()


async def _ollama_tag_list(base: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{base}/api/tags")
            if resp.status_code != 200:
                return []
            data = resp.json()
        return [str(m.get("name") or "") for m in (data.get("models") or []) if m.get("name")]
    except Exception:
        return []


async def ollama_pull(tag: str) -> dict[str, Any]:
    """用 Ollama 自己的 HTTP 接口拉模型，进度按 tag 记，刷新/重启后仍可看到。

    拉之前先查 ``/api/tags``：已经有的 tag 直接返回 already，不重复下载；
    上次中断留下的 partial blob 会由 Ollama 复用，再点同一个 tag 就是断点续传。
    """
    _load_pulls()
    cfg = load_config()
    base = platforms.endpoints(cfg).get("ollama", "")
    healthy, _, detail = await platforms._probe_external(base, "/api/tags")
    if not healthy:
        return {"ok": False, "msg": f"Ollama 服务没在运行（{base}）：请先在部署卡片点“启动”，再拉模型"}
    if PULL.get("running"):
        if ollama_tags.tag_key(PULL.get("tag") or "") == ollama_tags.tag_key(tag):
            return {"ok": True, "already": True, "running": True, "tag": tag,
                    "msg": f"{tag} 正在拉取（{PULL.get('pct', 0)}%），不用重复点"}
        return {"ok": False, "busy": True,
                "msg": f"正在拉取 {PULL.get('tag') or '模型'}，一次只能跑一个 Ollama 拉取任务"}
    tags = await _ollama_tag_list(base)
    if ollama_tags.tag_in(tag, tags):
        prev = pull_state(tag)
        _pull_set(tag=tag, running=False, ok=True, pct=100, step="已存在",
                  msg=f"{tag} 已经在 Ollama 中，无需重复下载", finished_at=time.time(),
                  resumable=False, error="")
        _save_pulls(force=True)
        return {"ok": True, "already": True, "tag": tag,
                "msg": f"{tag} 已拉取过，无需重复下载", "state": pull_state(tag)}
    prev = pull_state(tag)
    resume = bool(prev.get("resumable") or prev.get("partial_bytes"))
    _pull_set(tag=tag, running=True, pct=1, step="排队",
              msg=(f"继续拉取 {tag}，会复用已下载分片" if resume else f"准备拉取 {tag}"),
              ok=None, error="", started_at=time.time(), finished_at=0,
              updated_at=time.time(), digest="", bytes=0, total=0, resumable=True)
    _save_pulls(force=True)
    asyncio.create_task(_pull_task(base, tag))
    prefix = "继续拉取" if resume else "开始拉取"
    return {"ok": True, "tag": tag, "resume": resume,
            "msg": f"{prefix} {tag}；模型会落到 {ollama_models_dir(cfg)}"}


async def _pull_task(base: str, tag: str) -> None:
    from . import platform_models  # 拉完让模型列表缓存立刻失效
    try:
        _pull_set(tag=tag, pct=3, step="连接", msg=f"连接 {base} 拉取 {tag}")
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
                    digest = _digest_from_status(status)
                    if payload.get("error"):
                        raise RuntimeError(str(payload["error"])[:300])
                    if total and done:
                        pct = 5 + round(min(done / total, 0.99) * 85, 1)
                        _pull_set(tag=tag, pct=pct, step="下载", digest=digest,
                                  bytes=done, total=total,
                                  msg=f"{status or '下载'} {done / 2**20:.0f}/{total / 2**20:.0f} MB")
                    elif status:
                        _pull_set(tag=tag, step="处理", msg=status[:160],
                                  pct=max(PULL.get("pct", 0), 5), digest=digest or PULL.get("digest", ""))
        platform_models.invalidate()
        _pull_set(tag=tag, running=False, ok=True, pct=100, step="完成",
                  msg=f"{tag} 已拉取完成，可在“模型”页切换使用", finished_at=time.time(),
                  resumable=False, error="")
        _save_pulls(force=True)
    except Exception as exc:
        _pull_set(tag=tag, running=False, ok=False, step="已中断", error=str(exc)[:300],
                  msg=f"拉取 {tag} 失败：{str(exc)[:200]}（已保留分片，可继续拉取）",
                  finished_at=time.time(), resumable=True)
        _save_pulls(force=True)


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

    四个引擎口径一致：删程序与安装包缓存，保留“使用者自己下的模型”。
    系统安装（系统版 Ollama、桌面版 LM Studio）不归工作台管，直接拒绝并提示去系统里卸。
    """
    if key not in platforms.PLATFORMS:
        return {"ok": False, "msg": "未知平台"}
    if _state(key).get("running"):
        return {"ok": False, "msg": "这个平台正在部署，等它跑完再卸载"}
    if key == "ollama" and PULL.get("running"):
        return {"ok": False, "msg": f"正在拉取 {PULL.get('tag')}，等拉完再卸载"}

    cfg = load_config()
    # 删程序前先把模型收到 models 根下，避免老版本目录里的模型被一起删掉
    try:
        if key == "ollama":
            _migrate_ollama_models(cfg)
        elif key == "lmstudio":
            ensure_lmstudio_models(cfg, write_config=False)
    except Exception:
        log.exception("卸载前整理模型目录失败")
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
        if ours:
            await _kill_ours(proc)
        d = ollama_dir(cfg)
        models = ollama_models_dir(cfg)
        kept_models = str(models)
        for child in sorted(d.iterdir()) if d.exists() else []:
            if child.name == "models":
                continue
            targets.append(child)
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
    elif key in ("lmstudio", "vllm"):
        info = detect(key)
        if not info.get("managed"):
            label = "LM Studio" if key == "lmstudio" else "vLLM"
            return {"ok": False, "msg": f"{label} 不是工作台装的（系统安装或外部服务），工作台没有可删的东西；"
                                        f"要卸载请到系统程序列表里手动处理"}
        proc = PROCS.get(key)
        await _kill_ours(proc)
        d = platform_store.target(cfg, key)
        if not d.exists() or not _is_under(d, root):
            return {"ok": False, "msg": f"{key} 不在工作台目录里（{d}），请手动删除"}
        models = platform_store.models_dir(cfg, key)
        kept_models = str(models)
        for child in sorted(d.iterdir()):
            if child.name == "models":
                continue
            targets.append(child)
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
    else:
        return {"ok": False, "msg": "自定义平台是外部服务，工作台不接管卸载；请到那台机器上手动停服务"}

    # 安装包缓存也一起清：platforms\.downloads\<key>
    dl = platform_store.downloads(cfg) / key
    if dl.exists():
        freed += _dir_bytes(dl)
        shutil.rmtree(dl, ignore_errors=True)
    # 兼容老版本的扁平缓存（.downloads\<包名>）
    if key == "ollama":
        _, name = ollama_archive()
        for old in (root / ".downloads" / name,):
            if old.exists():
                freed += _dir_bytes(old)
                old.unlink(missing_ok=True)

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
                  "msg": "正在检查本机是否已安装", "started_at": now, "task": asyncio.current_task()}
    try:
        if key == "llama.cpp":
            ok, msg, skipped = await _deploy_llama(key, force)
        elif key == "ollama":
            ok, msg, skipped = await _deploy_ollama(key, endpoint, force)
        elif key == "lmstudio":
            ok, msg, skipped = await _deploy_lmstudio(key, endpoint, force)
        elif key == "vllm":
            ok, msg, skipped = await _deploy_vllm(key, endpoint, force)
        elif key == "custom":
            ok, msg, skipped = await _deploy_custom(key, endpoint)
        else:
            ok, msg, skipped = False, "不支持这个平台", False
        _set(key, running=False, ok=ok, skipped=skipped,
             pct=100 if ok else (get_state(key).get("pct") or 3), step="完成" if ok else "失败",
             msg=msg, error="" if ok else msg, finished_at=time.time())
        return {"ok": ok, "msg": msg, "skipped": skipped, "state": get_state(key)}
    except (DeployCancelled, installer.DownloadCancelled) as exc:
        _set(key, running=False, ok=False, cancelled=True, skipped=False,
             step="已取消", msg=f"{exc}（已下载的部分保留，再点一键部署会接着用）",
             error="", finished_at=time.time(), cancel=False, proc=None)
        return {"ok": False, "cancelled": True, "msg": str(exc), "state": get_state(key)}
    except Exception as exc:
        _set(key, running=False, ok=False, step="失败", msg=f"部署失败：{exc}",
             error=str(exc), finished_at=time.time())
        return {"ok": False, "msg": str(exc), "state": get_state(key)}
