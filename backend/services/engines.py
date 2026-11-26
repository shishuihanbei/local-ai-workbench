"""独立推理引擎检测。

有些模型（多模态、OCR、绘画、语音、向量）不能交给 llama.cpp 跑，需要
Transformers、vLLM、Diffusers 等独立引擎。这里只做“装没装”的检测和推荐，
不导入这些重量级包，避免拖慢接口。
"""
from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path
from typing import Any

from ..config import load_config
from . import hardware

# 引擎名 -> 需要在当前 Python 环境里能 import 的包（任意一个满足即可）
_ENGINE_PACKAGES: dict[str, tuple[str, ...]] = {
    "transformers": ("transformers",),
    "vllm": ("vllm",),
    "pytorch": ("torch",),
    "diffusers": ("diffusers",),
    "paddleocr": ("paddleocr", "paddle"),
    "funasr": ("funasr",),
    "sentencetransformers": ("sentence_transformers",),
    "onnx": ("onnxruntime",),
    "whisper": ("whisper", "faster_whisper"),
    "f5tts": ("f5_tts",),
    "fishspeech": ("fish_speech",),
    "mineru": ("mineru",),
    "surya": ("surya",),
    "kokoro": ("kokoro", "kokoro_onnx"),
}

_LABELS = {
    "transformers": "Transformers",
    "vllm": "vLLM",
    "pytorch": "PyTorch",
    "diffusers": "Diffusers",
    "paddleocr": "PaddleOCR",
    "funasr": "FunASR",
    "sentencetransformers": "SentenceTransformers",
    "onnx": "ONNX Runtime",
    "whisper": "faster-whisper",
    "f5tts": "F5-TTS",
    "fishspeech": "Fish Speech",
    "mineru": "MinerU",
    "surya": "Surya",
    "kokoro": "Kokoro",
}

_ALIASES = {
    "fasterwhisper": "whisper",
    "sentence_transformers": "sentencetransformers",
    "sentencetransformer": "sentencetransformers",
    "kokoroonnx": "kokoro",
}


def _spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def status(prof: dict[str, Any] | None = None) -> dict[str, Any]:
    packages = {name: _spec(name) for group in _ENGINE_PACKAGES.values() for name in group}
    torch = packages.get("torch", False)
    comfy_dir = Path(load_config()["platforms_dir"]) / "ComfyUI"
    installed = {
        "transformers": packages.get("transformers", False) and torch,
        "vllm": packages.get("vllm", False) or bool(shutil.which("vllm")),
        "pytorch": torch,
        "diffusers": packages.get("diffusers", False) and torch,
        "paddleocr": packages.get("paddleocr", False) or packages.get("paddle", False),
        "funasr": packages.get("funasr", False),
        "sentencetransformers": packages.get("sentence_transformers", False) and torch,
        "onnx": packages.get("onnxruntime", False),
        "whisper": packages.get("whisper", False) or packages.get("faster_whisper", False),
        "f5tts": packages.get("f5_tts", False),
        "fishspeech": packages.get("fish_speech", False),
        "mineru": packages.get("mineru", False),
        "surya": packages.get("surya", False),
        "kokoro": packages.get("kokoro", False) or packages.get("kokoro_onnx", False),
        "comfyui": bool(shutil.which("comfyui") or shutil.which("comfy") or comfy_dir.exists()),
        "ollama": bool(shutil.which("ollama")),
    }
    prof = prof or hardware.profile()
    gpus = prof.get("gpus") or []
    names = [str(g.get("name") or "") for g in gpus if isinstance(g, dict)]
    vram_gb = max([round(float(g.get("vram_mb") or 0) / 1024, 1)
                   for g in gpus if isinstance(g, dict)] or [0])
    # vLLM 跑 7B 级模型至少要有 8GB 显存；亮机卡/老卡不算“可用 GPU”
    gpu_usable = vram_gb >= 8
    return {
        "installed": installed,
        "gpu": bool(gpus),
        "gpu_usable": gpu_usable,
        "gpu_names": names[:4],
        "gpu_vram_gb": vram_gb,
        "python": prof.get("python", ""),
    }


def _parts(engine: str) -> list[str]:
    raw = str(engine or "").lower()
    parts = [re.sub(r"[-_\s]+", "", p) for p in re.split(r"[/,+]", raw) if p.strip()]
    parts = [_ALIASES.get(p, p) for p in parts]
    return parts or ["transformers"]


def _available_token(engine: str, st: dict[str, Any]) -> str:
    installed = st.get("installed", {})
    for part in _parts(engine):
        for token, packages in _ENGINE_PACKAGES.items():
            if part == token and any(installed.get(token) for _ in packages):
                return token
    # 组合写法（如 Ollama / Transformers）里任何一个已安装即可
    if "ollama" in _parts(engine) and installed.get("ollama"):
        return "ollama"
    return ""


def ready_for(engine: str, st: dict[str, Any] | None = None) -> bool:
    state = st or status()
    if "ollama" in _parts(engine) and state.get("installed", {}).get("ollama"):
        return True
    return bool(_available_token(engine, state))


def recommend(engine: str, st: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回推荐引擎、是否已安装、以及给用户看的说明。"""
    state = st or status()
    installed = state.get("installed", {})
    parts = _parts(engine)
    available = _available_token(engine, state)
    known = [p for p in parts if p in _ENGINE_PACKAGES or p in ("ollama", "comfyui", "tts")]

    if available:
        name = "Ollama" if available == "ollama" else _LABELS.get(available, available)
        return {"name": name, "ready": True, "installed": True,
                "text": f"本机已安装 {name}，可以直接下载模型。"}

    # 没装：按硬件和模型支持情况推荐一个最合适的
    prefer_vllm = "vllm" in parts and state.get("gpu_usable")
    if prefer_vllm:
        name, pkg = "vLLM", "vllm"
        text = "本机有 GPU，推荐用 vLLM；先到「部署」页一键部署 vLLM，装好后下载按钮才可用。"
    elif "transformers" in parts:
        name, pkg = "Transformers", "transformers"
        text = "本机未检测到 Transformers；先安装 transformers 和 torch，装好后下载按钮才可用。"
    elif "diffusers" in parts:
        name, pkg = "Diffusers", "diffusers"
        text = "本机未检测到 Diffusers；先安装 diffusers 和 torch，装好后下载按钮才可用。"
    elif "paddleocr" in parts:
        name, pkg = "PaddleOCR", "paddleocr"
        text = "本机未检测到 PaddleOCR；先安装 paddleocr，装好后下载按钮才可用。"
    elif "funasr" in parts:
        name, pkg = "FunASR", "funasr"
        text = "本机未检测到 FunASR；先安装 funasr，装好后下载按钮才可用。"
    elif "sentencetransformers" in parts:
        name, pkg = "SentenceTransformers", "sentence-transformers"
        text = "本机未检测到 SentenceTransformers；先安装 sentence-transformers 和 torch，装好后下载按钮才可用。"
    elif "onnx" in parts:
        name, pkg = "ONNX Runtime", "onnxruntime"
        text = "本机未检测到 ONNX Runtime；先安装 onnxruntime，装好后下载按钮才可用。"
    elif "whisper" in parts:
        name, pkg = "faster-whisper", "faster-whisper"
        text = "本机未检测到 faster-whisper；先安装 faster-whisper，装好后下载按钮才可用。"
    elif "f5tts" in parts:
        name, pkg = "F5-TTS", "f5-tts"
        text = "本机未检测到 F5-TTS；先安装 f5-tts 及 torch，装好后下载按钮才可用。"
    elif "fishspeech" in parts:
        name, pkg = "Fish Speech", "fish-speech"
        text = "本机未检测到 Fish Speech；先安装 fish-speech 及 torch，装好后下载按钮才可用。"
    elif "mineru" in parts:
        name, pkg = "MinerU", "mineru"
        text = "本机未检测到 MinerU；先安装 mineru，装好后下载按钮才可用。"
    elif "surya" in parts:
        name, pkg = "Surya", "surya-ocr"
        text = "本机未检测到 Surya；先安装 surya-ocr 及 torch，装好后下载按钮才可用。"
    elif "kokoro" in parts:
        name, pkg = "Kokoro", "kokoro-onnx"
        text = "本机未检测到 Kokoro ONNX；先安装 kokoro-onnx 和 onnxruntime，装好后下载按钮才可用。"
    elif "pytorch" in parts:
        name, pkg = "PyTorch", "torch"
        text = "本机未检测到 PyTorch；先安装 torch，装好后下载按钮才可用。"
    elif "vllm" in parts:
        name, pkg = "vLLM", "vllm"
        text = ("本机未检测到 vLLM；先到「部署」页部署 vLLM，装好后下载按钮才可用。"
                if state.get("gpu_usable") else
                "本机未检测到 vLLM，且显存不足 8GB，vLLM 可能跑不动；建议先用 Transformers 在 CPU 上跑。")
    elif "comfyui" in parts:
        name, pkg = "ComfyUI", "comfyui"
        text = "本机未检测到 ComfyUI；需要先单独部署 ComfyUI，装好后下载按钮才可用。"
    else:
        name = _LABELS.get(known[0], known[0].title()) if known else "独立引擎"
        pkg = ""
        text = "本机未检测到可用的独立引擎，请先安装对应引擎，装好后下载按钮才可用。"
    return {"name": name, "package": pkg, "ready": False, "installed": False, "text": text}


def describe(engine: str, st: dict[str, Any] | None = None) -> dict[str, Any]:
    state = st or status()
    rec = recommend(engine, state)
    return {
        "engine": engine,
        "ready": bool(rec["ready"]),
        "recommend": rec["name"],
        "package": rec.get("package", ""),
        "text": rec["text"],
        "gpu": bool(state.get("gpu")),
    }
