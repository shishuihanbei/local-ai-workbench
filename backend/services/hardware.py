"""硬件探测与模型可用性建议。"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

from ..config import IS_WINDOWS, CREATE_NO_WINDOW, llama_executable, load_config

_CPU_NAME_CACHE: str | None = None
_AVX2_CACHE: bool | None = None


def has_avx2() -> bool:
    """本机 CPU 是否支持 AVX2。LM Studio 0.0.27 的 lms 在 AVX2 缺失时会直接 0xC000001D。"""
    global _AVX2_CACHE
    if _AVX2_CACHE is not None:
        return _AVX2_CACHE
    ok = False
    try:
        if IS_WINDOWS:
            import ctypes
            # 27 = PF_AVX2_INSTRUCTIONS_AVAILABLE；40 不是 AVX2，旧写法会让所有机器都判成不支持
            ok = bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(27))
        elif platform.system().lower() == "darwin":
            ok = "AVX2" in _run(["sysctl", "-n", "machdep.cpu.features"]).upper()
        else:
            text = Path("/proc/cpuinfo").read_text(errors="ignore").lower()
            ok = "avx2" in text
    except Exception:
        ok = False
    _AVX2_CACHE = ok
    return ok



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


_PROFILE_CACHE: tuple[float, dict] = (0.0, {})


def profile(ttl: float = 8.0) -> dict:
    """本机硬件画像。控制台多个接口会同时要它，短缓存避免每次阻塞半秒。"""
    global _PROFILE_CACHE
    now = time.time()
    if _PROFILE_CACHE[1] and now - _PROFILE_CACHE[0] <= ttl:
        return dict(_PROFILE_CACHE[1])
    vm = psutil.virtual_memory()
    cfg = load_config()
    data = {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0],
        "cpu": cpu_name(),
        "cores": psutil.cpu_count(logical=True),
        "avx2": has_avx2(),
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "ram_free_gb": round(vm.available / 2**30, 1),
        "gpus": gpus(),
        "disks": disks(),
        "models_dir": cfg["models_dir"],
        "llama": llama_info(),
        "platform": platform.system().lower(),
    }
    _PROFILE_CACHE = (now, data)
    return dict(data)


def advise(size_bytes: int, prof: dict, ctx: int = 8192) -> dict:
    """根据模型体积与本机配置给出可用性建议。

    除了“内存够不够”，还要把纯 CPU 的实际体感说出来：18GB 以上的模型
    32GB 内存能装下，但 i7 这类老四核每秒只有 1 字左右，不能标成“可用”。
    """
    if not size_bytes:
        return {"level": "unknown", "label": "需确认", "text": "尚未获取模型体积，下载后可评估",
                "need_ram_gb": 0, "speed_tps": 0}
    size_gb = size_bytes / 2**30
    kv_gb = round(ctx / 8192 * 0.8, 1)          # 粗略 KV cache 估算
    need_ram = round(size_gb * 1.15 + kv_gb + 1.2, 1)
    vram = max([g["vram_mb"] for g in prof.get("gpus", [])], default=0) / 1024
    ram = prof.get("ram_total_gb", 0)
    free = prof.get("ram_free_gb", 0)
    # 老 CPU 的内存带宽约 25GB/s；每生成 1 token 要读一遍权重，按 Q4 体积粗估
    speed_tps = round(min(20.0, max(0.35, 25.0 / max(size_gb, 1.0))), 1)

    if vram and vram >= size_gb * 1.05:
        level, label = "good", "本机推荐"
        text = f"显存 {vram:.1f}GB 可全量放 GPU，推理速度约 {speed_tps} tok/s 以上"
    elif size_gb >= 16 and not (vram >= size_gb * 0.6):
        level, label = "warn", "勉强"
        text = (f"能装进 {ram}GB 内存，但纯 CPU 推理约 {speed_tps} tok/s，"
                "长回答要等很久；日常对话建议 8B 级")
    elif free >= need_ram + 2:
        level = "good" if size_gb <= 8 else "ok"
        label = "本机推荐" if level == "good" else "可用"
        text = (f"内存足够（约需 {need_ram}GB），CPU 推理约 {speed_tps} tok/s"
                + ("，日常首选" if level == "good" else "，适合当高质量备选"))
    elif free >= need_ram:
        level = "ok" if size_gb <= 8 else "warn"
        label = "可用" if level == "ok" else "勉强"
        text = (f"内存刚好够（约需 {need_ram}GB，空闲 {free}GB），CPU 推理约 {speed_tps} tok/s；"
                "建议先关掉其他程序")
    elif ram >= need_ram:
        level, label = "warn", "勉强"
        text = (f"总内存够但空闲不足（需 {need_ram}GB，当前空闲 {free}GB），会频繁换页、更慢；"
                "先关程序再试")
    else:
        level, label = "bad", "不建议"
        text = f"本机内存 {ram}GB 不足以承载（约需 {need_ram}GB）"
    return {"level": level, "label": label, "text": text,
            "need_ram_gb": need_ram, "size_gb": round(size_gb, 2), "speed_tps": speed_tps}
