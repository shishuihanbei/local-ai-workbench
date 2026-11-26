"""模型与部署平台的存储位置。

默认都在程序根目录下，不再写死某台机器的绝对路径：

    <程序根目录>/models                 放 .gguf 模型
    <程序根目录>/platforms/llama.cpp    放下载的 llama.cpp

老版本配置里如果是 `D:\\AI\\models` / `D:\\AI\\llama`，首次启动会尽量把
原有目录搬到新位置（同盘是重命名，很快）；搬不动就保留原路径并写日志。
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from ..config import BASE_DIR, default_llama_dir, default_models_dir, default_platforms_dir, load_config, save_config

log = logging.getLogger("workbench.storage")

# 老版本 README / 安装脚本写死的默认位置，仅用于迁移，不再作为默认值。
_LEGACY_MODELS = Path(r"D:\AI\models")
_LEGACY_LLAMA = Path(r"D:\AI\llama")


def _as_path(raw: object, fallback: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        return fallback
    p = Path(os.path.expandvars(text)).expanduser()
    if not p.is_absolute():
        p = BASE_DIR / p
    return p


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _move_into(src: Path, dst: Path) -> bool:
    """把 src 搬进 dst；目标已存在时逐个合并，不覆盖同名文件。"""
    if _same(src, dst) or not src.exists() or not src.is_dir():
        return False
    moved = False
    try:
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return True
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dst / item.name
            if target.exists():
                continue
            shutil.move(str(item), str(target))
            moved = True
        try:
            src.rmdir()
        except OSError:
            pass
    except Exception:
        log.exception("迁移目录失败：%s -> %s（保留原路径）", src, dst)
        return False
    return moved


def ensure() -> dict:
    """启动时调用：补默认键、建目录、迁移老版本写死的路径。"""
    cfg = load_config()
    changed: list[str] = []
    moved: list[str] = []

    models = _as_path(cfg.get("models_dir"), default_models_dir())
    if _same(models, _LEGACY_MODELS) and _move_into(models, default_models_dir()):
        models = default_models_dir()
        moved.append("models")
    if not models.exists():
        models = default_models_dir()
    try:
        models.mkdir(parents=True, exist_ok=True)
    except Exception:
        log.exception("创建模型目录失败：%s", models)

    platforms = _as_path(cfg.get("platforms_dir"), default_platforms_dir())
    if not platforms.exists():
        platforms = default_platforms_dir()
    try:
        platforms.mkdir(parents=True, exist_ok=True)
    except Exception:
        log.exception("创建平台目录失败：%s", platforms)

    llama = _as_path(cfg.get("llama_dir"), platforms / "llama.cpp")
    if _same(llama, _LEGACY_LLAMA) and _move_into(llama, platforms / "llama.cpp"):
        llama = platforms / "llama.cpp"
        moved.append("llama.cpp")
    if not llama.exists():
        llama = platforms / "llama.cpp"

    for key, value in (("models_dir", models), ("platforms_dir", platforms), ("llama_dir", llama)):
        if str(value) != str(cfg.get(key) or ""):
            cfg[key] = str(value)
            changed.append(key)
    if changed:
        save_config(cfg)
        log.info("存储路径已更新：%s%s", ", ".join(changed),
                 f"（已迁移 {', '.join(moved)}）" if moved else "")
    return status()


def status() -> dict:
    cfg = load_config()
    models = Path(cfg["models_dir"])
    platforms = Path(cfg.get("platforms_dir") or default_platforms_dir())
    llama = Path(cfg["llama_dir"])
    return {
        "root": str(BASE_DIR),
        "models_dir": str(models), "models_dir_exists": models.is_dir(),
        "platforms_dir": str(platforms), "platforms_dir_exists": platforms.is_dir(),
        "llama_dir": str(llama), "llama_dir_exists": llama.is_dir(),
        "defaults": {
            "models_dir": str(default_models_dir()),
            "platforms_dir": str(default_platforms_dir()),
            "llama_dir": str(default_llama_dir()),
        },
    }


def _require_dir(raw: object, label: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    p = Path(os.path.expandvars(text)).expanduser()
    if not p.is_absolute():
        raise ValueError(f"{label}请填绝对路径，例如 {default_models_dir()}")
    if p.exists() and not p.is_dir():
        raise ValueError(f"{label}指向的是一个文件：{p}")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"无法创建{label}：{exc}") from exc
    return p


def set_paths(models_dir: object = None, platforms_dir: object = None) -> dict:
    """保存自定义目录；只改配置，不自动搬已有文件。"""
    cfg = load_config()
    changed: list[str] = []
    if models_dir is not None:
        p = _require_dir(models_dir, "模型目录")
        if not _same(p, Path(cfg["models_dir"])):
            cfg["models_dir"] = str(p)
            changed.append("models_dir")
    if platforms_dir is not None:
        p = _require_dir(platforms_dir, "部署平台目录")
        if not _same(p, Path(cfg.get("platforms_dir") or default_platforms_dir())):
            cfg["platforms_dir"] = str(p)
            # llama.cpp 跟着平台目录走；已有的自定义 llama_dir 会被重置
            cfg["llama_dir"] = str(p / "llama.cpp")
            cfg["llama_bin"] = ""
            changed.extend(["platforms_dir", "llama_dir", "llama_bin"])
    if changed:
        save_config(cfg)
    return {"ok": True, "changed": changed, **status()}
