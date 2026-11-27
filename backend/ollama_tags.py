"""模型目录与 Ollama registry tag 的对应表。

同一份权重在不同引擎里的“形态”不同：llama.cpp 直接吃 ``.gguf`` 直链，
Ollama 则用自己仓库里的 tag（``ollama pull <tag>``），落盘是一堆 blob。
所以模型页不能只给一个统一“下载地址”，而要按引擎给出各自的安装方式。
"""
from __future__ import annotations

import re

# key -> Ollama 仓库里同名/同权重的 tag（只收录官方 registry 里确实存在的）
OLLAMA_TAGS: dict[str, str] = {
    "1.5b": "deepseek-r1:1.5b",
    "7b": "deepseek-r1:7b",
    "14b": "deepseek-r1:14b",
    "32b": "deepseek-r1:32b",
    "llama-8b": "deepseek-r1:8b",
    "llama-70b": "deepseek-r1:70b",
    "qwen25-7b": "qwen2.5:7b",
    "qwen25-coder-7b": "qwen2.5-coder:7b",
    "llama31-8b": "llama3.1:8b",
    "mistral-7b": "mistral:7b",
    "gemma2-9b": "gemma2:9b",
    "gemma2-2b": "gemma2:2b",
    # Ollama 官方 registry 里常用、但工作台内置清单单独收录的条目
    "ollama-qwen3-8b": "qwen3:8b",
    "ollama-qwen3-4b": "qwen3:4b",
    "ollama-llama32-3b": "llama3.2:3b",
    "ollama-llama32-1b": "llama3.2:1b",
    "ollama-gemma3-4b": "gemma3:4b",
    "ollama-phi4-mini": "phi4-mini",
    "ollama-qwen25-coder-14b": "qwen2.5-coder:14b",
}

# 输入框里允许出现的 tag 形态：qwen2.5:7b / hf.co/user/repo:Q4_K_M
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:[/:][A-Za-z0-9._-]+)*$")


def tag_for(key: str, alias: str = "") -> str:
    """返回该模型在 Ollama 里的 tag；没有对应项时返回空串。"""
    tag = OLLAMA_TAGS.get(str(key or ""), "")
    if tag:
        return tag
    return OLLAMA_TAGS.get(str(alias or ""), "")


def normalize_tag(raw: str) -> str:
    """清洗并校验用户输入的 tag；不合法时抛出 ValueError。"""
    tag = str(raw or "").strip()
    if not tag:
        raise ValueError("请填写要拉取的模型 tag，例如 qwen2.5:7b")
    if len(tag) > 120:
        raise ValueError("模型 tag 太长")
    if tag.lower().startswith("-") or not _TAG_RE.match(tag):
        raise ValueError("模型 tag 只能包含字母、数字、点、下划线、减号、斜杠和冒号")
    return tag
