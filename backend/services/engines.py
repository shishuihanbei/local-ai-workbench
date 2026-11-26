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

# 每个独立引擎的官网、下载页、安装方法和一键安装包。
# pip=[] 表示没有可靠的 pip 包，只能按官网/项目页手动安装。
ENGINE_CATALOG: dict[str, dict[str, Any]] = {
    "transformers": {
        "label": "Transformers",
        "site": "https://huggingface.co/docs/transformers/installation",
        "download": "https://pypi.org/project/transformers/",
        "pip": ["transformers", "torch", "accelerate"],
        "install": "pip install -U transformers torch accelerate",
        "note": "Hugging Face 官方推理库，Windows / Linux / macOS 都能用；torch 体积较大，首次安装要等几分钟。",
    },
    "vllm": {
        "label": "vLLM",
        "site": "https://docs.vllm.ai/en/latest/getting_started/installation.html",
        "download": "https://pypi.org/project/vllm/",
        "pip": ["vllm"],
        "install": "pip install -U vllm",
        "note": "高吞吐 GPU 推理引擎，官方主要支持 Linux + NVIDIA；Windows 需 WSL2 或单独 Linux 机器。",
    },
    "diffusers": {
        "label": "Diffusers",
        "site": "https://huggingface.co/docs/diffusers/installation",
        "download": "https://pypi.org/project/diffusers/",
        "pip": ["diffusers", "transformers", "accelerate", "torch"],
        "install": "pip install -U diffusers transformers accelerate torch",
        "note": "绘画、视频模型常用推理库；需要 PyTorch，显存越高越好。",
    },
    "paddleocr": {
        "label": "PaddleOCR",
        "site": "https://www.paddleocr.ai/",
        "download": "https://pypi.org/project/paddleocr/",
        "pip": ["paddleocr", "paddlepaddle"],
        "install": "pip install -U paddleocr paddlepaddle",
        "note": "中文 OCR、表格和版面分析；CPU 也能跑。",
    },
    "funasr": {
        "label": "FunASR",
        "site": "https://github.com/modelscope/FunASR",
        "download": "https://pypi.org/project/funasr/",
        "pip": ["funasr", "modelscope"],
        "install": "pip install -U funasr modelscope",
        "note": "阿里语音识别/合成工具包，适合 SenseVoice、CosyVoice。",
    },
    "sentencetransformers": {
        "label": "SentenceTransformers",
        "site": "https://sbert.net/docs/installation.html",
        "download": "https://pypi.org/project/sentence-transformers/",
        "pip": ["sentence-transformers", "torch"],
        "install": "pip install -U sentence-transformers torch",
        "note": "向量与重排序模型常用库；需要 PyTorch。",
    },
    "onnx": {
        "label": "ONNX Runtime",
        "site": "https://onnxruntime.ai/",
        "download": "https://pypi.org/project/onnxruntime/",
        "pip": ["onnxruntime"],
        "install": "pip install -U onnxruntime",
        "note": "ONNX 模型推理运行时，CPU 包体积小、安装快。",
    },
    "whisper": {
        "label": "faster-whisper",
        "site": "https://github.com/SYSTRAN/faster-whisper",
        "download": "https://pypi.org/project/faster-whisper/",
        "pip": ["faster-whisper"],
        "install": "pip install -U faster-whisper",
        "note": "Whisper 的快速推理实现，语音转写常用。",
    },
    "f5tts": {
        "label": "F5-TTS",
        "site": "https://github.com/SWivid/F5-TTS",
        "download": "https://pypi.org/project/f5-tts/",
        "pip": ["f5-tts", "torch"],
        "install": "pip install -U f5-tts torch",
        "note": "声音克隆/TTS 项目；安装包较大，建议有 NVIDIA 显卡。",
    },
    "fishspeech": {
        "label": "Fish Speech",
        "site": "https://github.com/fishaudio/fish-speech",
        "download": "https://github.com/fishaudio/fish-speech/archive/refs/heads/main.zip",
        "pip": [],
        "install": "git clone https://github.com/fishaudio/fish-speech.git，再按项目 README 安装",
        "note": "语音合成项目，依赖较多，建议按官方 README 手动部署。",
    },
    "mineru": {
        "label": "MinerU",
        "site": "https://github.com/opendatalab/MinerU",
        "download": "https://pypi.org/project/mineru/",
        "pip": ["mineru"],
        "install": "pip install -U mineru",
        "note": "PDF 解析、版面还原、公式表格提取。",
    },
    "surya": {
        "label": "Surya",
        "site": "https://github.com/datalab-to/surya",
        "download": "https://pypi.org/project/surya-ocr/",
        "pip": ["surya-ocr", "torch"],
        "install": "pip install -U surya-ocr torch",
        "note": "多语言 OCR、文本检测和阅读顺序；需要 PyTorch。",
    },
    "kokoro": {
        "label": "Kokoro",
        "site": "https://github.com/hexgrad/kokoro",
        "download": "https://pypi.org/project/kokoro-onnx/",
        "pip": ["kokoro-onnx", "onnxruntime"],
        "install": "pip install -U kokoro-onnx onnxruntime",
        "note": "轻量 TTS，ONNX 推理，CPU 也能跑。",
    },
    "comfyui": {
        "label": "ComfyUI",
        "site": "https://www.comfy.org/",
        "download": "https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip",
        "pip": [],
        "install": "下载压缩包解压到平台目录，再按 README 安装依赖并启动",
        "note": "节点式绘画/视频工作流，依赖 PyTorch 和自定义节点，建议单独部署。",
    },
    "ollama": {
        "label": "Ollama",
        "site": "https://ollama.com/",
        "download": "https://ollama.com/download",
        "pip": [],
        "install": "从官网下载安装包，安装后运行 ollama serve",
        "note": "本地模型运行器；本工作台「部署」页已提供一键安装。",
    },
}


def catalog(st: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    state = st or status()
    installed = state.get("installed", {})
    is_windows = str(state.get("platform") or "").lower() == "windows"
    out = []
    for key, info in ENGINE_CATALOG.items():
        blocked = ""
        if key == "vllm" and is_windows:
            blocked = "Windows 不能直接一键安装 vLLM，请用 WSL2 或 Linux 机器；也可以先装 Transformers。"
        one_click = bool(info.get("pip")) and not blocked
        out.append({
            "key": key, "label": info["label"], "site": info["site"],
            "download": info["download"], "install": info["install"],
            "note": info["note"], "installed": bool(installed.get(key)),
            "one_click": one_click, "blocked": blocked,
        })
    return out


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
        "platform": prof.get("platform", ""),
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
        return {"key": available, "name": name, "ready": True, "installed": True,
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
    rec_key = "ollama" if name == "Ollama" else next(
        (k for k, label in _LABELS.items() if label == name), "")
    return {"key": rec_key, "name": name, "package": pkg, "ready": False,
            "installed": False, "text": text}


def describe(engine: str, st: dict[str, Any] | None = None) -> dict[str, Any]:
    state = st or status()
    rec = recommend(engine, state)
    return {
        "engine": engine,
        "ready": bool(rec["ready"]),
        "recommend": rec["name"],
        "recommend_key": rec.get("key", ""),
        "package": rec.get("package", ""),
        "text": rec["text"],
        "gpu": bool(state.get("gpu")),
        "gpu_usable": bool(state.get("gpu_usable")),
    }
