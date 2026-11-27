"""模型目录与 Ollama registry tag 的对应表。

同一份权重在不同引擎里的“形态”不同：llama.cpp 直接吃 ``.gguf`` 直链，
Ollama 则用自己仓库里的 tag（``ollama pull <tag>``），落盘是一堆 blob。
所以模型页不能只给一个统一“下载地址”，而要按引擎给出各自的安装方式。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

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
    "ollama-qwen36-27b": "qwen3.6:27b",
    "ollama-qwen36-35b": "qwen3.6:35b-a3b",
    "ollama-qwen3-14b": "qwen3:14b",
    "ollama-qwen3-30b": "qwen3:30b-a3b",
    "ollama-qwen3-32b": "qwen3:32b",
    "ollama-qwen3-coder-30b": "qwen3-coder:30b",
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


def tag_key(tag: str) -> str:
    """比较 tag 是否同一个模型：忽略大小写和末尾的 ``:latest``。"""
    value = str(tag or "").strip().lower()
    if value.endswith(":latest"):
        value = value[:-7]
    return value


def tag_in(tag: str, tags) -> bool:
    """Ollama 的 ``/api/tags`` 与 ``/v1/models`` 命名可能带/不带 ``:latest``。"""
    key = tag_key(tag)
    return bool(key) and any(tag_key(t) == key for t in (tags or []))


def _manifest_name(parts: tuple[str, ...]) -> str:
    """把 manifests/registry/namespace/model/tag 还原成 Ollama 模型名。"""
    if len(parts) < 4:
        return ""
    registry, namespace, model, tag = parts[0], parts[1], parts[2], parts[3]
    if registry == "registry.ollama.ai":
        name = model if namespace == "library" else f"{namespace}/{model}"
    else:
        name = f"{registry}/{namespace}/{model}"
    return f"{name}:{tag}"


def local_tags(models_dir: str | Path) -> list[str]:
    """直接读 Ollama 的 manifests，得到本机已经完整落盘的 tag。

    Ollama 偶发会让 /api/tags 短暂落后于磁盘（刚 pull 完还没刷新索引），
    只靠 HTTP 列表就会出现“重启 Ollama 才认”的假象。这里以 manifest 为准，
    并校验模型层 blob 存在且非空，避免把只下了一半的 manifest 当已完成。
    """
    root = Path(models_dir) / "manifests"
    if not root.is_dir():
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            name = _manifest_name(tuple(rel.parts))
            if not name or name in seen:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            blobs = root.parent / "blobs"
            layers = list(data.get("layers") or [])
            config = data.get("config") if isinstance(data.get("config"), dict) else {}
            digest = str(config.get("digest") or "")
            if digest:
                layers.append({"digest": digest, "size": int(config.get("size") or 0),
                               "mediaType": "config"})
            ok = True
            for layer in layers:
                digest = str(layer.get("digest") or "")
                if not digest:
                    continue
                blob = blobs / digest.replace(":", "-")
                size = int(layer.get("size") or 0)
                if not blob.is_file():
                    ok = False
                    break
                # 模型层是权重，0 字节说明还没写完；配置/模板允许 0 字节占位
                if "image.model" in str(layer.get("mediaType") or "") and blob.stat().st_size <= 0:
                    ok = False
                    break
                if not size and blob.stat().st_size <= 0:
                    ok = False
                    break
            if ok:
                seen.add(name)
                tags.append(name)
        except Exception:
            continue
    tags.sort(key=tag_key)
    return tags


def manifest_refs(models_dir: str | Path) -> set[str]:
    """所有 manifest 里引用的 blob digest（sha256-xxx 形式），用于安全清理。"""
    root = Path(models_dir) / "manifests"
    out: set[str] = set()
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            config = data.get("config") if isinstance(data.get("config"), dict) else {}
            if config.get("digest"):
                out.add(str(config["digest"]).replace(":", "-"))
            for layer in data.get("layers") or []:
                if isinstance(layer, dict) and layer.get("digest"):
                    out.add(str(layer["digest"]).replace(":", "-"))
        except Exception:
            continue
    return out
