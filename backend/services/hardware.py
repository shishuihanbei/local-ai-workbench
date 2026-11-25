"""硬件探测与模型可用性建议。"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import psutil

from ..config import IS_WINDOWS, CREATE_NO_WINDOW, llama_executable, load_config

_CPU_NAME_CACHE: str | None = None


def _run(cmd: list[str], timeout: int = 8) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0)
        return (p.stdout or "") + (p.stderr or "")
    except Exception:
        return ""


def cpu_name() -> str:
    global _CPU_NAME_CACHE
    if _CPU_NAME_CACHE:
        return _CPU_NAME_CACHE
    name = platform.processor() or ""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except Exception:
            pass
    elif Path("/proc/cpuinfo").exists():
        for line in Path("/proc/cpuinfo").read_text(errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                name = line.split(":", 1)[1].strip()
                break
    _CPU_NAME_CACHE = name or "未知 CPU"
    return _CPU_NAME_CACHE


def gpus() -> list[dict]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader,nounits"])
    items = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2:
            try:
                items.append({"name": parts[0], "vram_mb": int(float(parts[1])),
                              "used_mb": int(float(parts[2])) if len(parts) > 2 else 0})
            except ValueError:
                continue
    return items


def disks() -> list[dict]:
    cfg = load_config()
    targets = [Path(cfg["models_dir"]).anchor or "/", Path(cfg["models_dir"])]
    seen, out = set(), []
    for t in targets:
        try:
            du = psutil.disk_usage(str(t))
        except Exception:
            continue
        key = str(Path(t).anchor or "/")          # 同一分区只报一次
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": key, "total_gb": round(du.total / 2**30, 1),
                    "free_gb": round(du.free / 2**30, 1)})
    return out


def llama_info() -> dict:
    cfg = load_config()
    exe = llama_executable(cfg)
    ver = ""
    if exe:
        lines = _run([str(exe), "--version"]).strip().splitlines()
        ver = lines[0][:120] if lines else ""
    return {"installed": bool(exe), "path": str(exe) if exe else "",
            "version": ver, "llama_dir": cfg["llama_dir"]}


def profile() -> dict:
    vm = psutil.virtual_memory()
    cfg = load_config()
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0],
        "cpu": cpu_name(),
        "cores": psutil.cpu_count(logical=True),
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "ram_free_gb": round(vm.available / 2**30, 1),
        "gpus": gpus(),
        "disks": disks(),
        "models_dir": cfg["models_dir"],
        "llama": llama_info(),
        "platform": platform.system().lower(),
    }


def advise(size_bytes: int, prof: dict, ctx: int = 8192) -> dict:
    """根据模型体积与本机配置给出可用性建议。"""
    if not size_bytes:
        return {"level": "unknown", "label": "未知", "text": "尚未获取模型体积，下载后可评估",
                "need_ram_gb": 0}
    size_gb = size_bytes / 2**30
    kv_gb = round(ctx / 8192 * 0.8, 1)          # 粗略 KV cache 估算
    need_ram = round(size_gb * 1.15 + kv_gb + 1.2, 1)
    vram = max([g["vram_mb"] for g in prof.get("gpus", [])], default=0) / 1024
    ram = prof.get("ram_total_gb", 0)
    free = prof.get("ram_free_gb", 0)

    if vram and vram >= size_gb * 1.05:
        level, label = "good", "流畅"
        text = f"显存 {vram:.1f}GB 可全量放 GPU，推理速度快"
    elif free >= need_ram + 2:
        level, label = "ok", "可用"
        text = f"内存足够（约需 {need_ram}GB），CPU 推理，速度中等"
    elif free >= need_ram:
        level, label = "ok", "可用"
        text = f"内存刚好够（约需 {need_ram}GB），建议关掉其他程序"
    elif ram >= need_ram:
        level, label = "warn", "勉强"
        text = f"总内存够但空闲不足（需 {need_ram}GB），会频繁换页、很慢"
    else:
        level, label = "bad", "不建议"
        text = f"本机内存 {ram}GB 不足以承载（约需 {need_ram}GB）"
    return {"level": level, "label": label, "text": text,
            "need_ram_gb": need_ram, "size_gb": round(size_gb, 2)}
