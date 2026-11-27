"""模型页的“优点 / 缺点”说明。

只有确实了解的项目才写详细条目；其余按用途给通用但可执行的结论，
保证模型页每一行都有可读的优缺点，而不是空白。
"""
from __future__ import annotations

from typing import Any

# key -> (优点, 缺点)。每项 2–3 条，控制台按行展示，太长会挤。
GUIDES: dict[str, dict[str, list[str]]] = {
    # ---- 本地已有 GGUF / R1 蒸馏
    "1.5b": {
        "pros": ["体积极小，机械硬盘也能秒开", "低配 CPU 也能流畅出字", "适合草稿、分类、简单问答"],
        "cons": ["知识和推理浅，复杂问题容易答偏", "不适合长文写作或代码任务"],
    },
    "7b": {
        "pros": ["7B 里性价比较高，日常问答够用", "中文表达自然，CPU 上仍能出字", "Q4 约 4.7GB，内存压力小"],
        "cons": ["复杂推理、数学和多步任务一般", "长上下文容易丢细节"],
    },
    "14b": {
        "pros": ["理解和写作明显强于 7B", "32GB 内存可以稳定加载", "适合总结、改写、中等难度问答"],
        "cons": ["CPU 推理约 2–3 tok/s，长回答要等", "9GB 体积，开机后内存占用明显"],
    },
    "32b": {
        "pros": ["本地模型里质量较高，复杂推理更稳", "适合严肃写作、分析和多步任务"],
        "cons": ["Q4 约 18.5GB，加载慢、占内存", "纯 CPU 每秒约 1 字，日常对话不现实", "最好有 24GB 显存"],
    },
    "qwen3-8b": {
        "pros": ["0528 新版 R1 蒸馏，推理链更完整", "中文数学、逻辑题表现好于普通 7B", "约 5GB，32GB 机器轻松装下"],
        "cons": ["仍然只有 8B 的知识面", "思考模式输出长，CPU 上等待时间偏长"],
    },
    "llama-8b": {
        "pros": ["Llama 3.1 底座，英文指令跟随稳定", "生态和工具兼容性好"],
        "cons": ["中文语感弱于 Qwen 系", "8B 知识面和复杂推理有限"],
    },
    "llama-70b": {
        "pros": ["70B 级别，质量和知识面明显更高", "适合高质量英文写作和复杂分析"],
        "cons": ["Q4 约 39.6GB，普通机器装不下", "即使装下，纯 CPU 也几乎不可用"],
    },
    "v4-flash": {
        "pros": ["284B MoE，单次只激活约 13B，理论效率高", "知识面和上限远高于 30B 级"],
        "cons": ["IQ2_S 仍要 88GB，需要大内存或多卡", "低比特量化会损失精度，部署门槛高"],
    },
    # ---- 扩展 GGUF
    "qwen25-7b": {
        "pros": ["中文通用对话稳，幻觉相对少", "7B 体积小，CPU 上速度可接受", "适合日常问答、写作、摘要"],
        "cons": ["上下文和工具调用不如 Qwen3 系", "复杂推理需要更长思考链时偏弱"],
    },
    "llama31-8b": {
        "pros": ["英文写作和指令跟随强", "工具调用、结构化输出成熟"],
        "cons": ["中文表达不如 Qwen 自然", "8B 参数限制知识深度"],
    },
    "mistral-7b": {
        "pros": ["轻量、英文写作顺", "部署简单，老机器也能跑"],
        "cons": ["中文能力弱", "知识面和长上下文一般"],
    },
    "gemma2-9b": {
        "pros": ["Google 开源，多语言和英文不错", "9B 在质量和速度间比较均衡"],
        "cons": ["中文不是强项", "生态和工具适配不如 Llama/Qwen"],
    },
    "gemma2-2b": {
        "pros": ["极小体积，低配机器可用", "启动快，适合简单问答和草稿"],
        "cons": ["知识面和推理很有限", "不适合正式写作、代码和复杂任务"],
    },
    "yi15-9b": {
        "pros": ["中文对话自然，9B 均衡", "适合中文内容改写和问答"],
        "cons": ["工具调用和代码能力一般", "社区生态小于 Qwen/Llama"],
    },
    "qwen25-coder-7b": {
        "pros": ["代码补全、解释、重构针对性强", "7B 体积，CPU 上还能用", "支持多种主流语言"],
        "cons": ["通用聊天和长文写作弱于同尺寸通用模型", "仓库级跨文件任务仍吃力"],
    },
    # ---- Ollama Qwen3 / Qwen3.6
    "ollama-qwen36-27b": {
        "pros": ["Qwen3.6 原生视觉，能看图、截图、视频", "256K 上下文，长文档和仓库级任务强", "Agentic coding、工具调用和 STEM 明显提升", "Apache 2.0，可商用"],
        "cons": ["Q4 约 18GB，32GB 机器加载后很紧", "纯 CPU 推理约 1 tok/s，日常对话会明显卡", "视觉能力需要 Ollama 新版运行时支持"],
    },
    "ollama-qwen36-35b": {
        "pros": ["35B MoE 只激活约 3B，同体积下速度更好", "256K 上下文 + 原生视觉", "适合 Agent、长文档和复杂工具调用"],
        "cons": ["整体仍要 23GB 内存/显存", "本机空闲内存不足时容易换页", "MoE 对运行时版本要求更高"],
    },
    "ollama-qwen3-8b": {
        "pros": ["Qwen3 原生思考/非思考切换", "中文对话和推理均衡", "Ollama 一条 tag 就能拉取"],
        "cons": ["8B 知识面有限", "思考模式在 CPU 上等待较长"],
    },
    "ollama-qwen3-4b": {
        "pros": ["体积小、启动快，低配首选", "中文短问答和草稿够用", "Ollama 管理方便"],
        "cons": ["复杂推理和长文写作弱", "知识面窄，容易答得笼统"],
    },
    "ollama-qwen3-14b": {
        "pros": ["14B 质量明显高于 8B", "中文理解、写作和中等推理稳", "9GB，32GB 内存可稳定加载"],
        "cons": ["CPU 推理约 2–3 tok/s", "长上下文时内存和等待都增加"],
    },
    "ollama-qwen3-30b": {
        "pros": ["30B MoE / 3B 激活，推理效率高", "知识面和复杂任务强于 14B", "适合 Agent 和多步工具调用"],
        "cons": ["仍要约 19GB 内存/显存", "本机纯 CPU 加载和首字等待明显"],
    },
    "ollama-qwen3-32b": {
        "pros": ["32B Dense，复杂推理和写作质量高", "适合严肃分析、长文和难题"],
        "cons": ["约 20GB，32GB 机器余量很小", "纯 CPU 约 1 tok/s，不建议日常"],
    },
    "ollama-qwen3-coder-30b": {
        "pros": ["代码与 Agent 专用，仓库级任务强", "30B MoE / 3B 激活，效率高于 Dense 30B", "256K 上下文，适合读大项目"],
        "cons": ["约 19GB，内存压力大", "通用中文聊天不如同尺寸通用模型", "本机 CPU 下首字和长输出都慢"],
    },
    "ollama-qwen25-coder-14b": {
        "pros": ["代码能力比 7B Coder 强一档", "9GB，32GB 机器可加载", "适合补全、重构和报错分析"],
        "cons": ["CPU 推理偏慢", "仓库级跨文件理解仍不如 30B 级"],
    },
    "ollama-llama32-3b": {
        "pros": ["3B 轻量，启动和出字都快", "英文对话和简单指令稳定"],
        "cons": ["中文一般", "复杂任务和知识问答有限"],
    },
    "ollama-llama32-1b": {
        "pros": ["1B 超轻量，几乎任何机器能跑", "适合简单分类、草稿、测试链路"],
        "cons": ["只能做很浅的任务", "中文和知识面都弱"],
    },
    "ollama-gemma3-4b": {
        "pros": ["4B 轻量，多语言对话", "英文和简单视觉场景可用"],
        "cons": ["中文不如 Qwen", "复杂推理能力有限"],
    },
    "ollama-phi4-mini": {
        "pros": ["小体积英文推理不错", "适合结构化问答和简单工具调用"],
        "cons": ["中文能力弱", "知识面窄"],
    },
}

# 没单独写条目的模型，按用途兜底；保证每行都有“优点/缺点”可看。
CATEGORY_FALLBACK: dict[str, tuple[list[str], list[str]]] = {
    "text": (["本地离线可用，数据不出机器", "对话、写作、摘要等通用任务"],
             ["知识面和推理受参数量限制", "长上下文会额外占内存"]),
    "code": (["代码补全、解释、重构", "可离线处理私有代码"],
             ["仓库级跨文件任务仍吃力", "需要足够上下文和内存"]),
    "vision": (["看图问答、截图理解、OCR、图表分析", "能处理文档和界面截图"],
               ["需要独立视觉引擎和投影文件", "显存/内存要求高于纯文本模型"]),
    "ocr": (["中文 OCR、表格和版面分析", "适合扫描件和 PDF 解析"],
            ["需要单独安装 OCR 引擎", "复杂版面仍需人工校对"]),
    "image": (["文生图、风格化和配图", "可本地部署，隐私可控"],
              ["显存要求高，CPU 出图很慢", "需要 ComfyUI/Diffusers 等独立引擎"]),
    "video": (["文生视频/图生视频", "适合短视频和概念片"],
              ["显存和磁盘要求最高", "生成时间长，需独立引擎"]),
    "audio": (["语音识别或语音合成", "可离线处理音频"],
              ["需要 FunASR/Whisper 等引擎", "长音频处理耗时"]),
    "embedding": (["文本向量化，适合知识库检索", "多语言语义匹配"],
                  ["需要向量引擎", "模型效果依赖切分和索引策略"]),
    "rerank": (["检索结果重排序，提升命中率", "适合和向量模型配套"],
               ["需要额外推理步骤", "会增加检索延迟"]),
}

_QUANT_WORDS = ("q4", "q5", "q8", "iq", "fp16", "bf16", "gguf", "mlx", "safetensors")


def _clean_note(note: str) -> list[str]:
    parts = []
    for raw in str(note or "").split("·"):
        text = raw.strip()
        if not text or text.lower().startswith("ollama tag"):
            continue
        low = text.lower()
        if any(w in low for w in _QUANT_WORDS):
            continue
        parts.append(text)
    return parts[:2]


def guide_for(key: str, category: str, note: str, engine: str,
              size_bytes: int, engine_recommend: str = "") -> dict[str, list[str]]:
    """返回 {pros, cons}；先取逐模型说明，再补引擎差异。"""
    item = GUIDES.get(str(key or ""))
    if item:
        pros, cons = list(item["pros"]), list(item["cons"])
    else:
        base_pros, base_cons = CATEGORY_FALLBACK.get(category or "text", CATEGORY_FALLBACK["text"])
        pros, cons = list(base_pros), list(base_cons)
        note_parts = _clean_note(note)
        if note_parts:
            pros = note_parts + pros

    eng = str(engine or "").strip()
    if eng.lower() == "ollama":
        pros.append("Ollama 一条 tag 拉取，跨平台省事")
        cons.append("依赖 Ollama 服务；模型是 blobs，不便单文件搬走")
    elif eng.lower() == "llama.cpp":
        pros.append("GGUF 单文件，可离线、可整包搬走")
    elif eng and eng.lower() not in ("cluster", "custom"):
        need = engine_recommend or eng
        cons.append(f"需要先装 {need}，不能直接用 llama.cpp 跑")
    if size_bytes >= 16 * 1024 ** 3:
        cons.append("体积 16GB 以上，加载慢且吃内存")

    def _dedupe(items: list[str]) -> list[str]:
        out: list[str] = []
        for x in items:
            if x and x not in out:
                out.append(x)
        return out[:4]

    return {"pros": _dedupe(pros), "cons": _dedupe(cons)}


def recommendation_summary(prof: dict[str, Any]) -> str:
    gpus = prof.get("gpus") or []
    gpu = ""
    if gpus:
        g = max(gpus, key=lambda x: int(x.get("vram_mb") or 0))
        gpu = f"{g.get('name') or 'GPU'} {int(g.get('vram_mb') or 0) / 1024:.0f}GB 显存"
    else:
        gpu = "无独显"
    return (f"{prof.get('cpu') or '本机 CPU'} · {prof.get('cores') or 0} 核 · "
            f"{prof.get('ram_total_gb') or 0}GB 内存（空闲 {prof.get('ram_free_gb') or 0}GB） · {gpu}")
