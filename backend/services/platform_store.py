"""平台安装产物的统一落脚点。

四个本地引擎（llama.cpp / Ollama / LM Studio / vLLM）的下载、解压、程序本体、
模型、pip 与 Hugging Face 缓存，全部写在下面这几个目录里：

    <根目录>\\platforms\\llama.cpp|ollama|lmstudio|vllm   程序本体
    <根目录>\\platforms\\.downloads                     下载的安装包 / 压缩包
    <根目录>\\platforms\\.tmp                           解压与临时文件
    <根目录>\\platforms\\<引擎>\\models                  引擎自己的模型（vLLM 等）
    <根目录>\\models                                    GGUF / Hugging Face 仓库
    <根目录>\\data\\cache                                pip / Hugging Face / 其它缓存

这样整包搬走、整包删除都是一件事，不会往 %TEMP%、%LOCALAPPDATA%、~/.cache
这些系统目录里丢东西。
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, IS_WINDOWS, default_models_dir, default_platforms_dir, load_config

DOWNLOAD_DIRNAME = ".downloads"
TMP_DIRNAME = ".tmp"

ENGINE_LABELS = {
    "llama.cpp": "llama.cpp",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "vllm": "vLLM",
}

# 这四个引擎由工作台自己装、自己删；custom 是外部服务，不参与
MANAGED_ENGINES = ("llama.cpp", "ollama", "lmstudio", "vllm")


def platforms_root(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    raw = str(cfg.get("platforms_dir") or "").strip()
    return Path(raw).expanduser() if raw else default_platforms_dir()


def downloads(cfg: dict[str, Any] | None = None) -> Path:
    """安装包缓存：platforms\\.downloads（可按引擎再分一层子目录）。"""
    return platforms_root(cfg) / DOWNLOAD_DIRNAME


def download_dir(cfg: dict[str, Any] | None, key: str) -> Path:
    d = downloads(cfg) / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def tmp_root(cfg: dict[str, Any] | None = None) -> Path:
    d = platforms_root(cfg) / TMP_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def workbench_tmp(cfg: dict[str, Any] | None = None, prefix: str = "work") -> Path:
    """在 platforms\\.tmp 下开一个唯一临时目录，替掉系统 %TEMP%。"""
    d = tmp_root(cfg) / f"{prefix}-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def target(cfg: dict[str, Any] | None, key: str) -> Path:
    """引擎程序本体的落位目录。llama.cpp 沿用 llama_dir，保持老配置可用。"""
    cfg = cfg or load_config()
    if key == "llama.cpp":
        raw = str(cfg.get("llama_dir") or "").strip()
        return Path(raw).expanduser() if raw else platforms_root(cfg) / "llama.cpp"
    return platforms_root(cfg) / key


def models_dir(cfg: dict[str, Any] | None, key: str) -> Path:
    """模型统一放在 models 下：llama.cpp / vLLM 用 models 根，Ollama / LM Studio 用子目录。

    Ollama 的 registry 结构是 blobs + manifests，LM Studio 要 publisher/model/xxx.gguf
    的层级，两者都不能和平铺的 .gguf 混在同一层；所以在 models 下各给一层子目录，
    物理上仍然只有一个模型根目录，备份/搬走只动 models 一处。
    """
    cfg = cfg or load_config()
    base = Path(str(cfg.get("models_dir") or "").strip()).expanduser() if str(cfg.get("models_dir") or "").strip() else default_models_dir()
    if key in ("ollama", "lmstudio"):
        return base / key
    if key in ("llama.cpp", "vllm", "shared"):
        return base
    return base


def cache_root() -> Path:
    d = DATA_DIR / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pip_cache(cfg: dict[str, Any] | None = None) -> Path:
    d = cache_root() / "pip"
    d.mkdir(parents=True, exist_ok=True)
    return d


def hf_home(cfg: dict[str, Any] | None = None) -> Path:
    d = cache_root() / "huggingface"
    d.mkdir(parents=True, exist_ok=True)
    return d


def child_env(cfg: dict[str, Any] | None = None, extra: dict[str, str] | None = None,
              home: str | Path | None = None) -> dict[str, str]:
    """给子进程用的环境：临时目录、pip 缓存、HF 缓存都指回工作台目录。"""
    cfg = cfg or load_config()
    env = os.environ.copy()
    tmp = tmp_root(cfg)
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    env["TMPDIR"] = str(tmp)
    env["PIP_CACHE_DIR"] = str(pip_cache(cfg))
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["HF_HOME"] = str(hf_home(cfg))
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["XDG_CACHE_HOME"] = str(cache_root())
    if home:
        env["HOME"] = str(home)
        if IS_WINDOWS:
            env["USERPROFILE"] = str(home)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def inside(path: str | Path, cfg: dict[str, Any] | None = None) -> bool:
    """路径是否在工作台自己的目录里（防止误删用户别处的东西）。"""
    try:
        Path(path).expanduser().resolve().relative_to(platforms_root(cfg).resolve())
        return True
    except Exception:
        return False


def dir_bytes(path: Path) -> int:
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


def human(n: int) -> str:
    if n >= 2**30:
        return f"{n / 2**30:.2f} GB"
    if n >= 2**20:
        return f"{n / 2**20:.0f} MB"
    if n >= 2**10:
        return f"{n / 2**10:.0f} KB"
    return f"{n} B"


def summary(cfg: dict[str, Any] | None = None, with_sizes: bool = True) -> list[dict[str, Any]]:
    """下载/安装目录清单：给控制台“文件都在哪”面板和文档共用。

    只给程序、安装包、临时、缓存算大小；模型目录可能几百 GB，不扫盘。
    """
    cfg = cfg or load_config()
    root = platforms_root(cfg)
    rows: list[dict[str, Any]] = []
    for key in MANAGED_ENGINES:
        d = target(cfg, key)
        rows.append({
            "key": f"engine:{key}",
            "label": f"{ENGINE_LABELS[key]} 程序",
            "path": str(d),
            "kind": "program",
            "exists": d.exists(),
            "bytes": dir_bytes(d) if (with_sizes and d.exists()) else 0,
        })
    dl = downloads(cfg)
    rows.append({"key": "downloads", "label": "安装包缓存", "path": str(dl), "kind": "downloads",
                 "exists": dl.exists(),
                 "bytes": dir_bytes(dl) if (with_sizes and dl.exists()) else 0})
    tmp = root / TMP_DIRNAME
    rows.append({"key": "tmp", "label": "临时解压", "path": str(tmp), "kind": "tmp",
                 "exists": tmp.exists(),
                 "bytes": dir_bytes(tmp) if (with_sizes and tmp.exists()) else 0})
    md = models_dir(cfg, "shared")
    rows.append({"key": "models", "label": "模型目录", "path": str(md), "kind": "models",
                 "exists": md.exists(), "bytes": -1})
    for key, label in (("ollama", "Ollama 模型"), ("lmstudio", "LM Studio 模型")):
        d = models_dir(cfg, key)
        rows.append({"key": f"models:{key}", "label": label, "path": str(d), "kind": "models",
                     "exists": d.exists(), "bytes": -1})
    cache = cache_root()
    rows.append({"key": "cache", "label": "pip / HF 缓存", "path": str(cache), "kind": "cache",
                 "exists": cache.exists(),
                 "bytes": dir_bytes(cache) if (with_sizes and cache.exists()) else 0})
    data = DATA_DIR
    rows.append({"key": "data", "label": "数据与日志", "path": str(data), "kind": "data",
                 "exists": data.exists(), "bytes": -1})
    for row in rows:
        row["human"] = "—" if int(row["bytes"] or 0) < 0 else human(int(row["bytes"] or 0))
    return rows
