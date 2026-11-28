"""SQLite 访问层：建表、迁移、常用查询封装。"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Iterable

import aiosqlite

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',           -- admin | user
    disabled INTEGER NOT NULL DEFAULT 0,
    allowed_models TEXT NOT NULL DEFAULT '*',   -- '*' 全部；或 JSON 数组 ["7b","deepseek-chat"]
    memory_enabled INTEGER NOT NULL DEFAULT 0,  -- 用户自己开的长期记忆开关
    created_at REAL NOT NULL,
    last_login_at REAL,
    last_login_ip TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    ip TEXT,
    ua TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auth_identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,                     -- username | phone | email | qq | wechat
    provider_uid TEXT NOT NULL,                 -- 用户名 / 手机号 / 邮箱 / openid
    display_name TEXT,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    last_login_at REAL,
    UNIQUE(provider, provider_uid)
);
CREATE INDEX IF NOT EXISTS idx_auth_identities_user ON auth_identities(user_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '默认密钥',
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_used_at REAL,
    last_ip TEXT,
    last_scope TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '新对话',
    model TEXT,
    system_prompt TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                          -- user | assistant | system
    content TEXT NOT NULL DEFAULT '',
    reasoning TEXT,
    tokens INTEGER NOT NULL DEFAULT 0,
    meta TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'fact',            -- fact | preference | explicit
    content TEXT NOT NULL,
    content_norm TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',          -- auto | manual
    conversation_id INTEGER,
    weight REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 1,
    hits INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_used_at REAL,
    UNIQUE(user_id, content_norm)
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, active, updated_at DESC);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'file',            -- image | text | document | file
    text_content TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, id DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts DESC);

CREATE TABLE IF NOT EXISTS models (
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    family TEXT,
    note TEXT,
    filename TEXT NOT NULL,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    repo TEXT,
    fit TEXT,
    sort INTEGER NOT NULL DEFAULT 0,
    category TEXT DEFAULT 'text',
    engine TEXT DEFAULT 'llama.cpp',
    homepage TEXT DEFAULT '',
    installable INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'openai',        -- openai | local | azure
    base_url TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',
    models TEXT NOT NULL DEFAULT '',            -- 逗号分隔的模型名
    price_in REAL NOT NULL DEFAULT 0,           -- 每百万输入 token 单价
    price_out REAL NOT NULL DEFAULT 0,
    timeout REAL NOT NULL DEFAULT 120,
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    strategy TEXT NOT NULL DEFAULT 'local_first',  -- local_first | cloud_first | manual
    provider_id INTEGER,
    model_map TEXT NOT NULL DEFAULT '{}',          -- JSON: 逻辑模型 -> 供应商模型
    fallback TEXT NOT NULL DEFAULT '[]',           -- JSON: provider_id 列表
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',
    weight INTEGER NOT NULL DEFAULT 1,
    max_concurrency INTEGER NOT NULL DEFAULT 4,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'unknown',       -- unknown | online | offline
    models TEXT NOT NULL DEFAULT '[]',            -- JSON: /v1/models 返回的模型名
    latency_ms INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    last_check_at REAL,
    last_ok_at REAL,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cluster_nodes_enabled ON cluster_nodes(enabled, status);

CREATE TABLE IF NOT EXISTS cluster_pools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,                    -- 对外统一模型名
    strategy TEXT NOT NULL DEFAULT 'weighted_least', -- weighted_least | round_robin
    timeout REAL NOT NULL DEFAULT 30,
    retries INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id INTEGER NOT NULL REFERENCES cluster_pools(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES cluster_nodes(id) ON DELETE CASCADE,
    remote_model TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(pool_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_cluster_members_pool ON cluster_members(pool_id, enabled);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    scene TEXT NOT NULL DEFAULT 'chat',
    content TEXT NOT NULL DEFAULT '',
    variables TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    traffic_pct INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    released_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    user_id INTEGER,
    conversation_id INTEGER,
    route_id INTEGER,
    provider TEXT,
    provider_id INTEGER,
    model TEXT,
    stream INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'ok',            -- ok | error | stopped
    error TEXT,
    prompt_version TEXT,
    prompt_hash TEXT,
    prompt_rendered TEXT,
    params_json TEXT,
    decision_json TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_estimated INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    price_in REAL NOT NULL DEFAULT 0,
    price_out REAL NOT NULL DEFAULT 0,
    ttft_ms INTEGER NOT NULL DEFAULT 0,
    total_ms INTEGER NOT NULL DEFAULT 0,
    queue_ms INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    cache_id TEXT,
    experiment_id TEXT,
    bucket INTEGER NOT NULL DEFAULT 0,
    shadow_of TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_req_ts ON requests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_req_model ON requests(model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_req_status ON requests(status, created_at DESC);

CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    trace_id TEXT NOT NULL,
    kind TEXT NOT NULL,                           -- llm | retrieval | tool
    name TEXT,
    start_ms INTEGER NOT NULL DEFAULT 0,
    dur_ms INTEGER NOT NULL DEFAULT 0,
    attrs_json TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_span_req ON spans(request_id);

CREATE TABLE IF NOT EXISTS cache_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL DEFAULT 'default',
    kind TEXT NOT NULL DEFAULT 'exact',
    prompt_hash TEXT NOT NULL,
    answer TEXT NOT NULL,
    model_key TEXT,
    hits INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cache_key ON cache_entries(scope, kind, prompt_hash, model_key);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    traffic_pct INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    config_json TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_key TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',     -- running | done | error | cancelled
    bytes INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS kb_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    scope TEXT NOT NULL DEFAULT 'global',        -- global 公共库 | personal 个人库
    title TEXT NOT NULL,
    source TEXT,
    chars INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at REAL NOT NULL
);
"""

KB_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
    doc_id UNINDEXED, title, content, tokenize='unicode61'
);
"""

# 预置模型清单（来自既有 D:\\AI\\models 目录，可在「模型管理」中改/加）
MODEL_SEED: list[dict[str, Any]] = [
    dict(key="1.5b", alias="deepseek-r1-1.5b", label="R1-Distill-Qwen-1.5B", family="Qwen 蒸馏",
         note="最快 · 约 15 tok/s · 适合低配", fit="good", sort=1,
         filename="DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
         total_bytes=1117320512, repo="DeepSeek-R1-Distill-Qwen-1.5B-GGUF"),
    dict(key="7b", alias="deepseek-r1-7b", label="R1-Distill-Qwen-7B", family="Qwen 蒸馏",
         note="均衡 · 约 6-8 tok/s · 日常首选", fit="good", sort=2,
         filename="DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
         total_bytes=4683073216, repo="DeepSeek-R1-Distill-Qwen-7B-GGUF"),
    dict(key="14b", alias="deepseek-r1-14b", label="R1-Distill-Qwen-14B", family="Qwen 蒸馏",
         note="高质量 · 约 3-5 tok/s · 需 16GB 内存", fit="good", sort=3,
         filename="DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf",
         total_bytes=8988109952, repo="DeepSeek-R1-Distill-Qwen-14B-GGUF"),
    dict(key="32b", alias="deepseek-r1-32b", label="R1-Distill-Qwen-32B", family="Qwen 蒸馏",
         note="18.5GB · 需 32GB 内存 · 很慢", fit="tight", sort=4,
         filename="DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf",
         total_bytes=19851335552, repo="DeepSeek-R1-Distill-Qwen-32B-GGUF"),
    dict(key="qwen3-8b", alias="deepseek-r1-0528-8b", label="R1-0528-Qwen3-8B", family="0528 新版",
         note="新版 R1 蒸馏 · 推理更稳", fit="good", sort=5,
         filename="DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf",
         total_bytes=5027782720, repo="DeepSeek-R1-0528-Qwen3-8B-GGUF"),
    dict(key="llama-8b", alias="deepseek-r1-llama-8b", label="R1-Distill-Llama-8B", family="Llama 蒸馏",
         note="Llama 3.1 底座", fit="good", sort=6,
         filename="DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf",
         total_bytes=4920736320, repo="DeepSeek-R1-Distill-Llama-8B-GGUF"),
    dict(key="llama-70b", alias="deepseek-r1-llama-70b", label="R1-Distill-Llama-70B", family="Llama 蒸馏",
         note="39.6GB · 需 64GB 内存", fit="no", sort=7,
         filename="DeepSeek-R1-Distill-Llama-70B-Q4_K_M.gguf",
         total_bytes=42520395616, repo="DeepSeek-R1-Distill-Llama-70B-GGUF"),
    dict(key="v4-flash", alias="deepseek-v4-flash", label="DeepSeek-V4-Flash (IQ2_S)", family="V4 MoE",
         note="284B 总参 / 13B 激活 · 88GB · 需大内存或多卡", fit="no", sort=8,
         filename="DeepSeek-V4-Flash.IQ2_S.gguf",
         total_bytes=88019539296, repo="bullerwins/DeepSeek-V4-Flash-GGUF"),
]

# 扩展模型目录：文字/代码模型可直接下载；绘画、视频、语音、向量等需要独立引擎，
# 先作为“清单收录”，不提供 llama.cpp 下载入口，避免下载后无法运行。
MODEL_CATALOG_EXTRAS: list[dict[str, Any]] = [
    # ---- 文字 / 对话（GGUF，可直接下载）
    dict(key="qwen25-7b", alias="qwen2.5-7b", label="Qwen2.5-7B-Instruct", family="Qwen2.5",
         note="通用对话 · 中文表现好 · Q4_K_M", fit="good", sort=9, category="text",
         filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf", total_bytes=4683073952,
         repo="lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/Qwen2.5-7B-Instruct-GGUF"),
    dict(key="llama31-8b", alias="llama-3.1-8b", label="Llama-3.1-8B-Instruct", family="Llama 3.1",
         note="英文与指令跟随强 · Q4_K_M", fit="good", sort=10, category="text",
         filename="Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf", total_bytes=4920739168,
         repo="lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF"),
    dict(key="mistral-7b", alias="mistral-7b", label="Mistral-7B-Instruct-v0.3", family="Mistral",
         note="轻量通用 · 英文写作 · Q4_K_M", fit="good", sort=11, category="text",
         filename="Mistral-7B-Instruct-v0.3-Q4_K_M.gguf", total_bytes=4372812000,
         repo="lmstudio-community/Mistral-7B-Instruct-v0.3-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/Mistral-7B-Instruct-v0.3-GGUF"),
    dict(key="gemma2-9b", alias="gemma-2-9b", label="Gemma-2-9B-it", family="Gemma 2",
         note="Google 开源 · 多语言 · Q4_K_M", fit="good", sort=12, category="text",
         filename="gemma-2-9b-it-Q4_K_M.gguf", total_bytes=5761057728,
         repo="lmstudio-community/gemma-2-9b-it-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/gemma-2-9b-it-GGUF"),
    dict(key="gemma2-2b", alias="gemma-2-2b", label="Gemma-2-2B-it", family="Gemma 2",
         note="超轻量 · 低配机器可用 · Q4_K_M", fit="good", sort=13, category="text",
         filename="gemma-2-2b-it-Q4_K_M.gguf", total_bytes=1708582752,
         repo="lmstudio-community/gemma-2-2b-it-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/gemma-2-2b-it-GGUF"),
    dict(key="yi15-9b", alias="yi-1.5-9b", label="Yi-1.5-9B-Chat", family="Yi",
         note="中文对话 · 9B 均衡 · Q4_K_M", fit="good", sort=14, category="text",
         filename="Yi-1.5-9B-Chat-Q4_K_M.gguf", total_bytes=5328957952,
         repo="lmstudio-community/Yi-1.5-9B-Chat-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/Yi-1.5-9B-Chat-GGUF"),

    # ---- 代码 / 编程（GGUF，可直接下载）
    dict(key="qwen25-coder-7b", alias="qwen2.5-coder-7b", label="Qwen2.5-Coder-7B-Instruct", family="Qwen Coder",
         note="代码补全 / 解释 / 重构 · Q4_K_M", fit="good", sort=15, category="code",
         filename="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf", total_bytes=4683074048,
         repo="lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF",
         homepage="https://modelscope.cn/models/lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF"),

    # ---- 多模态 / 视觉理解（需独立推理引擎）
    dict(key="qwen25-vl-7b", label="Qwen2.5-VL-7B-Instruct", family="Qwen VL",
         note="看图问答、OCR、图表理解；需视觉投影文件", sort=101, category="vision",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers / vLLM",
         homepage="https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct"),
    dict(key="llava-v16-7b", label="LLaVA-v1.6-Mistral-7B", family="LLaVA",
         note="图像问答；需要视觉投影和 Mistral 底座", sort=102, category="vision",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers",
         homepage="https://huggingface.co/liuhaotian/llava-v1.6-mistral-7b"),
    dict(key="minicpm-v-26", label="MiniCPM-V 2.6", family="MiniCPM-V",
         note="端侧多模态，支持图片与多轮问答", sort=103, category="vision",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers",
         homepage="https://huggingface.co/openbmb/MiniCPM-V-2_6"),
    dict(key="internvl2-8b", label="InternVL2-8B", family="InternVL",
         note="通用视觉理解，适合图文问答", sort=104, category="vision",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers / vLLM",
         homepage="https://huggingface.co/OpenGVLab/InternVL2-8B"),
    dict(key="pixtral-12b", label="Pixtral-12B", family="Pixtral",
         note="Mistral 多模态，图文理解", sort=105, category="vision",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="vLLM",
         homepage="https://huggingface.co/mistralai/Pixtral-12B-2409"),

    # ---- OCR / 文档识别
    dict(key="paddleocr", label="PaddleOCR", family="PaddleOCR",
         note="中文 OCR、表格和版面分析", sort=111, category="ocr",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="PaddleOCR",
         homepage="https://github.com/PaddlePaddle/PaddleOCR"),
    dict(key="got-ocr2", label="GOT-OCR2.0", family="GOT-OCR",
         note="通用 OCR，支持公式、表格和手写", sort=112, category="ocr",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers",
         homepage="https://huggingface.co/stepfun-ai/GOT-OCR2_0"),
    dict(key="surya", label="Surya OCR", family="Surya",
         note="多语言 OCR、文本检测和阅读顺序", sort=113, category="ocr",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="PyTorch",
         homepage="https://github.com/VikParuchuri/surya"),
    dict(key="mineru", label="MinerU", family="MinerU",
         note="PDF 解析、版面还原、公式表格提取", sort=114, category="ocr",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="PyTorch",
         homepage="https://github.com/opendatalab/MinerU"),

    # ---- 绘画 / 图像生成（ComfyUI / Diffusers）
    dict(key="flux1-dev", label="FLUX.1-dev", family="FLUX",
         note="高质量文生图，显存要求较高", sort=121, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/black-forest-labs/FLUX.1-dev"),
    dict(key="sdxl-base", label="SDXL Base 1.0", family="Stable Diffusion XL",
         note="1024 分辨率通用绘画底座", sort=122, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0"),
    dict(key="sd15", label="Stable Diffusion 1.5", family="Stable Diffusion",
         note="生态最全、低显存可跑", sort=123, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/runwayml/stable-diffusion-v1-5"),
    dict(key="sd35-large", label="Stable Diffusion 3.5 Large", family="Stable Diffusion 3.5",
         note="新一代 SD，画质和提示词跟随更好", sort=124, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/stabilityai/stable-diffusion-3.5-large"),
    dict(key="kolors", label="Kolors", family="Kolors",
         note="中文文生图，快手开源", sort=125, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/Kwai-Kolors/Kolors"),
    dict(key="hunyuan-dit", label="HunyuanDiT", family="HunyuanDiT",
         note="中文绘画，腾讯混元文生图", sort=126, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/Tencent-Hunyuan/HunyuanDiT"),
    dict(key="playground-v25", label="Playground v2.5", family="Playground",
         note="1024 美学向文生图", sort=127, category="image",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ComfyUI / Diffusers",
         homepage="https://huggingface.co/playgroundai/playground-v2.5-1024px-aesthetic"),

    # ---- 视频生成
    dict(key="wan21-t2v-14b", label="Wan2.1-T2V-14B", family="Wan",
         note="文生视频，阿里万相 14B", sort=131, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/Wan-AI/Wan2.1-T2V-14B"),
    dict(key="wan21-i2v-14b", label="Wan2.1-I2V-14B", family="Wan",
         note="图生视频，阿里万相 14B", sort=132, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P"),
    dict(key="hunyuanvideo", label="HunyuanVideo", family="HunyuanVideo",
         note="腾讯混元视频生成，质量高、显存要求高", sort=133, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/tencent/HunyuanVideo"),
    dict(key="ltx-video", label="LTX-Video", family="LTX",
         note="快速视频生成，适合短视频", sort=134, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/Lightricks/LTX-Video"),
    dict(key="cogvideox-5b", label="CogVideoX-5B", family="CogVideoX",
         note="智谱开源视频生成", sort=135, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/THUDM/CogVideoX-5b"),
    dict(key="mochi-1", label="Mochi-1 Preview", family="Mochi",
         note="Genmo 开源视频生成", sort=136, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/genmoai/mochi-1-preview"),
    dict(key="svd-xt", label="Stable Video Diffusion XT", family="SVD",
         note="图生视频，Stability 开源", sort=137, category="video",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Diffusers",
         homepage="https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt"),

    # ---- 语音 / 音频
    dict(key="whisper-large-v3", label="Whisper Large v3", family="Whisper",
         note="多语言语音识别，准确率高", sort=141, category="audio",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Whisper",
         homepage="https://huggingface.co/openai/whisper-large-v3"),
    dict(key="sensevoice-small", label="SenseVoice Small", family="SenseVoice",
         note="中文语音识别、语种和情绪识别", sort=142, category="audio",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="FunASR",
         homepage="https://modelscope.cn/models/iic/SenseVoiceSmall"),
    dict(key="cosyvoice2", label="CosyVoice2-0.5B", family="CosyVoice",
         note="中文语音合成，支持音色克隆", sort=143, category="audio",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="FunASR / TTS",
         homepage="https://modelscope.cn/models/iic/CosyVoice2-0.5B"),
    dict(key="fish-speech-15", label="Fish Speech 1.5", family="Fish Speech",
         note="多语言 TTS，音色克隆", sort=144, category="audio",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="PyTorch / TTS",
         homepage="https://huggingface.co/fishaudio/fish-speech-1.5"),
    dict(key="kokoro-82m", label="Kokoro-82M", family="Kokoro",
         note="超轻量英文 TTS", sort=145, category="audio",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="ONNX / TTS",
         homepage="https://huggingface.co/hexgrad/Kokoro-82M"),
    dict(key="f5-tts", label="F5-TTS", family="F5-TTS",
         note="高质量零样本语音合成", sort=146, category="audio",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="PyTorch / TTS",
         homepage="https://huggingface.co/SWivid/F5-TTS"),

    # ---- 向量 / 检索
    dict(key="bge-m3", label="BGE-M3", family="BGE",
         note="多语言向量 + 稀疏 + 多向量检索", sort=151, category="embedding",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="SentenceTransformers",
         homepage="https://huggingface.co/BAAI/bge-m3"),
    dict(key="bge-large-zh", label="BGE-Large-ZH-v1.5", family="BGE",
         note="中文语义检索常用", sort=152, category="embedding",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="SentenceTransformers",
         homepage="https://huggingface.co/BAAI/bge-large-zh-v1.5"),
    dict(key="nomic-embed", label="Nomic Embed Text v1.5", family="Nomic",
         note="长文本英文向量检索", sort=153, category="embedding",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Ollama / Transformers",
         homepage="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5"),
    dict(key="jina-embeddings-v3", label="Jina Embeddings v3", family="Jina",
         note="多语言长文本向量", sort=154, category="embedding",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers",
         homepage="https://huggingface.co/jinaai/jina-embeddings-v3"),
    dict(key="multilingual-e5-large", label="Multilingual E5 Large", family="E5",
         note="多语言语义检索", sort=155, category="embedding",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="SentenceTransformers",
         homepage="https://huggingface.co/intfloat/multilingual-e5-large"),

    # ---- 重排序
    dict(key="bge-reranker-v2-m3", label="BGE Reranker v2-m3", family="BGE",
         note="多语言重排序，配合 BGE-M3 使用", sort=161, category="rerank",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="SentenceTransformers",
         homepage="https://huggingface.co/BAAI/bge-reranker-v2-m3"),
    dict(key="bge-reranker-large", label="BGE Reranker Large", family="BGE",
         note="中文重排序经典模型", sort=162, category="rerank",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="SentenceTransformers",
         homepage="https://huggingface.co/BAAI/bge-reranker-large"),
    dict(key="jina-reranker-v2", label="Jina Reranker v2", family="Jina",
         note="多语言重排序", sort=163, category="rerank",
         filename="", total_bytes=0, repo="", fit="unknown", installable=0, engine="Transformers",
         homepage="https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual"),
]

# Ollama 官方 registry 里常用的模型：单独一批补进内置清单，让使用者先在清单里
# 看到有哪些可选（而不是只知道一个输入框）。这些条目不走 GGUF 下载，安装方式是
# `ollama pull <tag>`，前端按 engine=Ollama 给“用 Ollama 拉取”按钮。
# 只补一次，用户删掉的条目不会每次启动又回来。
OLLAMA_MODEL_CATALOG: list[dict[str, Any]] = [
    # 2026 年主流：Qwen3.6 原生视觉 + 长上下文；先收录最常被问到的 27B 与 35B-A3B
    dict(key="ollama-qwen36-27b", alias="qwen3.6-27b", label="Qwen3.6-27B", family="Qwen3.6",
         note="Ollama tag · 27B Dense · 18GB · 256K 上下文 · 原生看图/视频", fit="tight", sort=45,
         category="text", filename="", total_bytes=19327352832, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3.6"),
    dict(key="ollama-qwen36-35b", alias="qwen3.6-35b-a3b", label="Qwen3.6-35B-A3B", family="Qwen3.6",
         note="Ollama tag · 35B MoE / 3B 激活 · 23GB · 256K · 原生看图", fit="no", sort=46,
         category="text", filename="", total_bytes=24696061952, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3.6"),
    dict(key="ollama-qwen3-14b", alias="qwen3-14b", label="Qwen3-14B", family="Qwen3",
         note="Ollama tag · 14B · 9GB · 40K 上下文 · 通用均衡", fit="good", sort=47,
         category="text", filename="", total_bytes=9663676416, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3"),
    dict(key="ollama-qwen3-30b", alias="qwen3-30b-a3b", label="Qwen3-30B-A3B", family="Qwen3",
         note="Ollama tag · 30B MoE / 3B 激活 · 19GB · 40K · 多专家推理", fit="tight", sort=48,
         category="text", filename="", total_bytes=20399123712, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3"),
    dict(key="ollama-qwen3-32b", alias="qwen3-32b", label="Qwen3-32B", family="Qwen3",
         note="Ollama tag · 32B Dense · 20GB · 40K · 高质量推理", fit="no", sort=49,
         category="text", filename="", total_bytes=21474836480, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3"),
    dict(key="ollama-qwen3-coder-30b", alias="qwen3-coder-30b", label="Qwen3-Coder-30B-A3B", family="Qwen Coder",
         note="Ollama tag · 30B MoE / 3B 激活 · 19GB · 256K · 代码与 Agent", fit="tight", sort=62,
         category="code", filename="", total_bytes=20399123712, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3-coder"),
    dict(key="ollama-qwen3-8b", alias="qwen3-8b", label="Qwen3-8B", family="Qwen3",
         note="Ollama 官方 tag · 中文对话与推理 · 约 5.2GB", fit="good", sort=55, category="text",
         filename="", total_bytes=5583457485, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3"),
    dict(key="ollama-qwen3-4b", alias="qwen3-4b", label="Qwen3-4B", family="Qwen3",
         note="Ollama 官方 tag · 轻量通用 · 约 2.6GB", fit="good", sort=56, category="text",
         filename="", total_bytes=2791728742, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen3"),
    dict(key="ollama-llama32-3b", alias="llama3.2-3b", label="Llama-3.2-3B-Instruct", family="Llama 3.2",
         note="Ollama 官方 tag · 英文与轻量对话 · 约 2.0GB", fit="good", sort=57, category="text",
         filename="", total_bytes=2147483648, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/llama3.2"),
    dict(key="ollama-llama32-1b", alias="llama3.2-1b", label="Llama-3.2-1B-Instruct", family="Llama 3.2",
         note="Ollama 官方 tag · 超轻量，低配可用 · 约 1.3GB", fit="good", sort=58, category="text",
         filename="", total_bytes=1395864371, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/llama3.2"),
    dict(key="ollama-gemma3-4b", alias="gemma3-4b", label="Gemma-3-4B-it", family="Gemma 3",
         note="Ollama 官方 tag · 多语言对话 · 约 3.3GB", fit="good", sort=59, category="text",
         filename="", total_bytes=3543348019, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/gemma3"),
    dict(key="ollama-phi4-mini", alias="phi4-mini", label="Phi-4-mini-instruct", family="Phi",
         note="Ollama 官方 tag · 小体积英文推理 · 约 2.5GB", fit="good", sort=60, category="text",
         filename="", total_bytes=2684354560, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/phi4-mini"),
    dict(key="ollama-qwen25-coder-14b", alias="qwen2.5-coder-14b", label="Qwen2.5-Coder-14B-Instruct", family="Qwen Coder",
         note="Ollama 官方 tag · 更强代码补全 · 约 9GB", fit="tight", sort=61, category="code",
         filename="", total_bytes=9663676416, repo="", installable=0, engine="Ollama",
         homepage="https://ollama.com/library/qwen2.5-coder"),
]

# 非 llama.cpp 模型必须写清后期要安装的独立引擎，方便按引擎分批接入
ENGINE_REQUIREMENTS = {
    "llava-v16-7b": "vLLM / Transformers",
    "minicpm-v-26": "Transformers",
    "got-ocr2": "Transformers",
    "surya": "Surya",
    "mineru": "MinerU",
    "kolors": "ComfyUI",
    "hunyuan-dit": "Diffusers",
    "wan21-t2v-14b": "ComfyUI / Diffusers",
    "wan21-i2v-14b": "ComfyUI / Diffusers",
    "hunyuanvideo": "ComfyUI / Diffusers",
    "ltx-video": "ComfyUI / Diffusers",
    "cogvideox-5b": "Diffusers",
    "mochi-1": "ComfyUI / Diffusers",
    "svd-xt": "ComfyUI / Diffusers",
    "whisper-large-v3": "faster-whisper",
    "cosyvoice2": "FunASR",
    "fish-speech-15": "Fish Speech",
    "kokoro-82m": "Kokoro ONNX",
    "f5-tts": "F5-TTS",
    "nomic-embed": "Ollama / SentenceTransformers",
    "jina-reranker-v2": "SentenceTransformers",
}

# 需独立引擎、且权重托管在 Hugging Face 的模型：整仓库下载用。
# 代码仓库型项目（PaddleOCR、Surya、MinerU、ComfyUI）不在这里，避免下错东西。
HF_MODEL_REPOS = {
    "qwen25-vl-7b": "Qwen/Qwen2.5-VL-7B-Instruct",
    "llava-v16-7b": "liuhaotian/llava-v1.6-mistral-7b",
    "minicpm-v-26": "openbmb/MiniCPM-V-2_6",
    "internvl2-8b": "OpenGVLab/InternVL2-8B",
    "pixtral-12b": "mistralai/Pixtral-12B-2409",
    "got-ocr2": "stepfun-ai/GOT-OCR2_0",
    "flux1-dev": "black-forest-labs/FLUX.1-dev",
    "sdxl-base": "stabilityai/stable-diffusion-xl-base-1.0",
    "sd15": "stable-diffusion-v1-5/stable-diffusion-v1-5",
    "sd35-large": "stabilityai/stable-diffusion-3.5-large",
    "kolors": "Kwai-Kolors/Kolors",
    "hunyuan-dit": "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers",
    "playground-v25": "playgroundai/playground-v2.5-1024px-aesthetic",
    "wan21-t2v-14b": "Wan-AI/Wan2.1-T2V-14B",
    "wan21-i2v-14b": "Wan-AI/Wan2.1-I2V-14B-720P",
    "hunyuanvideo": "tencent/HunyuanVideo",
    "ltx-video": "Lightricks/LTX-Video",
    "cogvideox-5b": "THUDM/CogVideoX-5b",
    "mochi-1": "genmo/mochi-1-preview",
    "svd-xt": "stabilityai/stable-video-diffusion-img2vid-xt",
    "whisper-large-v3": "openai/whisper-large-v3",
    "sensevoice-small": "FunAudioLLM/SenseVoiceSmall",
    "cosyvoice2": "FunAudioLLM/CosyVoice2-0.5B",
    "fish-speech-15": "fishaudio/fish-speech-1.5",
    "kokoro-82m": "hexgrad/Kokoro-82M",
    "f5-tts": "SWivid/F5-TTS",
    "bge-m3": "BAAI/bge-m3",
    "bge-large-zh": "BAAI/bge-large-zh-v1.5",
    "nomic-embed": "nomic-ai/nomic-embed-text-v1.5",
    "jina-embeddings-v3": "jinaai/jina-embeddings-v3",
    "multilingual-e5-large": "intfloat/multilingual-e5-large",
    "bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3",
    "bge-reranker-large": "BAAI/bge-reranker-large",
    "jina-reranker-v2": "jinaai/jina-reranker-v2-base-multilingual",
}


def model_repo(key: str, repo: str = "") -> str:
    """数据库老版本 repo 为空时，用内置映射补上。"""
    return repo or HF_MODEL_REPOS.get(key, "")


MS_BASE = "https://modelscope.cn/api/v1/models/%s/repo?Revision=master&FilePath=%s"


def model_url(repo: str, filename: str) -> str:
    if "/" not in repo:
        repo = "lmstudio-community/" + repo
    return MS_BASE % (repo, filename)


async def connect() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


# 常驻共享连接：多协程访问时复用同一条 aiosqlite 连接，由异步锁串行化，
# 避免每个请求都新建连接和后台线程（100 人并发下这部分开销最明显）。
_shared: aiosqlite.Connection | None = None
_shared_lock: asyncio.Lock | None = None
_shared_lock_loop = None


def _shared_guard() -> asyncio.Lock:
    """按当前事件循环取锁。

    模块级的 ``asyncio.Lock`` 会绑定第一次 await 时的循环，测试/脚本里多次
    ``asyncio.run`` 再复用它就会报 "bound to a different event loop"，所以这里
    换循环时新建一把锁；共享连接本身不属于任何循环（aiosqlite 在工作线程里跑，
    回调走调用方 future 的循环），继续复用同一个连接，避免留下关不掉的线程。
    """
    global _shared_lock, _shared_lock_loop
    loop = asyncio.get_running_loop()
    if _shared_lock is None or _shared_lock_loop is not loop:
        _shared_lock = asyncio.Lock()
        _shared_lock_loop = loop
    return _shared_lock


async def _shared_connection() -> aiosqlite.Connection:
    global _shared
    if _shared is None:
        _shared = await aiosqlite.connect(DB_PATH)
        _shared.row_factory = aiosqlite.Row
        await _shared.execute("PRAGMA journal_mode=WAL")
        await _shared.execute("PRAGMA foreign_keys=ON")
    return _shared


async def close_shared() -> None:
    """进程退出时关闭共享连接；初始化/迁移仍走独立的 connect()。"""
    global _shared
    async with _shared_guard():
        if _shared is not None:
            try:
                await _shared.close()
            except Exception:
                pass
            _shared = None


async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(r["name"] == column for r in rows)


async def _add_column(db: aiosqlite.Connection, table: str, column: str, ddl: str) -> None:
    if not await _column_exists(db, table, column):
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def _migration_001_model_columns(db: aiosqlite.Connection) -> None:
    """旧库补齐模型分类字段和用户模型权限字段。"""
    await _add_column(db, "models", "alias", "alias TEXT DEFAULT ''")
    await _add_column(db, "models", "category", "category TEXT DEFAULT 'text'")
    await _add_column(db, "models", "engine", "engine TEXT DEFAULT 'llama.cpp'")
    await _add_column(db, "models", "homepage", "homepage TEXT DEFAULT ''")
    await _add_column(db, "models", "installable", "installable INTEGER NOT NULL DEFAULT 1")
    await _add_column(db, "users", "allowed_models", "allowed_models TEXT DEFAULT '*'")


async def _migration_002_chat_uploads(db: aiosqlite.Connection) -> None:
    """聊天文件上传：正文提取结果与原始文件分开保存。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS uploads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "name TEXT NOT NULL,stored_name TEXT NOT NULL,mime TEXT NOT NULL DEFAULT '',"
        "size INTEGER NOT NULL DEFAULT 0,kind TEXT NOT NULL DEFAULT 'file',"
        "text_content TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, id DESC)")


async def _migration_003_memories(db: aiosqlite.Connection) -> None:
    """长期记忆：按用户保存可开关的跨对话事实与偏好。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "kind TEXT NOT NULL DEFAULT 'fact',content TEXT NOT NULL,content_norm TEXT NOT NULL,"
        "source TEXT NOT NULL DEFAULT 'auto',conversation_id INTEGER,"
        "weight REAL NOT NULL DEFAULT 1.0,active INTEGER NOT NULL DEFAULT 1,"
        "hits INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,updated_at REAL NOT NULL,"
        "last_used_at REAL,UNIQUE(user_id, content_norm))")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_user "
        "ON memories(user_id, active, updated_at DESC)")


async def _migration_004_personal_scope(db: aiosqlite.Connection) -> None:
    """个人知识库与用户级长期记忆开关。

    kb_docs 旧数据统一归入 global，避免升级后公共库突然消失；
    users.memory_enabled 默认 0，长期记忆仍然默认关闭。
    """
    await _add_column(db, "kb_docs", "scope", "scope TEXT NOT NULL DEFAULT 'global'")
    await _add_column(db, "users", "memory_enabled",
                      "memory_enabled INTEGER NOT NULL DEFAULT 0")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_docs_scope ON kb_docs(scope,user_id,id DESC)")


async def _migration_005_kb_preferences(db: aiosqlite.Connection) -> None:
    """知识库开关默认关闭，并把公共/个人来源拆成用户可多选的两项。"""
    await _add_column(db, "users", "kb_personal_enabled",
                      "kb_personal_enabled INTEGER NOT NULL DEFAULT 0")
    await _add_column(db, "users", "kb_use_public",
                      "kb_use_public INTEGER NOT NULL DEFAULT 0")
    await _add_column(db, "users", "kb_use_personal",
                      "kb_use_personal INTEGER NOT NULL DEFAULT 1")


async def _migration_006_library(db: aiosqlite.Connection) -> None:
    """独立资料库：复用文档存储，用 module 区分知识库/资料库。"""
    await _add_column(db, "kb_docs", "module", "module TEXT NOT NULL DEFAULT 'kb'")
    await _add_column(db, "kb_docs", "uses", "uses INTEGER NOT NULL DEFAULT 0")
    await _add_column(db, "kb_docs", "last_used_at", "last_used_at REAL")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_docs_module ON kb_docs(module,scope,id DESC)")
    await _add_column(db, "users", "library_personal_enabled",
                      "library_personal_enabled INTEGER NOT NULL DEFAULT 0")
    await _add_column(db, "users", "library_use_global",
                      "library_use_global INTEGER NOT NULL DEFAULT 0")
    await _add_column(db, "users", "library_use_personal",
                      "library_use_personal INTEGER NOT NULL DEFAULT 1")


async def _migration_007_library_folders_tags(db: aiosqlite.Connection) -> None:
    """资料库分类：文件夹和标签，知识库文档保持空值。"""
    await _add_column(db, "kb_docs", "folder", "folder TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "kb_docs", "tags", "tags TEXT NOT NULL DEFAULT ''")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_docs_folder "
        "ON kb_docs(module,scope,folder,id DESC)")


async def _migration_008_cluster(db: aiosqlite.Connection) -> None:
    """多机算力池：节点、统一模型池和成员关系。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS cluster_nodes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,"
        "base_url TEXT NOT NULL,api_key TEXT NOT NULL DEFAULT '',"
        "weight INTEGER NOT NULL DEFAULT 1,max_concurrency INTEGER NOT NULL DEFAULT 4,"
        "enabled INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL DEFAULT 'unknown',"
        "models TEXT NOT NULL DEFAULT '[]',latency_ms INTEGER NOT NULL DEFAULT 0,"
        "last_error TEXT NOT NULL DEFAULT '',last_check_at REAL,last_ok_at REAL,"
        "note TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_cluster_nodes_enabled ON cluster_nodes(enabled, status)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS cluster_pools ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,"
        "strategy TEXT NOT NULL DEFAULT 'weighted_least',timeout REAL NOT NULL DEFAULT 30,"
        "retries INTEGER NOT NULL DEFAULT 1,enabled INTEGER NOT NULL DEFAULT 1,"
        "note TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS cluster_members ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "pool_id INTEGER NOT NULL REFERENCES cluster_pools(id) ON DELETE CASCADE,"
        "node_id INTEGER NOT NULL REFERENCES cluster_nodes(id) ON DELETE CASCADE,"
        "remote_model TEXT NOT NULL,weight INTEGER NOT NULL DEFAULT 1,"
        "enabled INTEGER NOT NULL DEFAULT 1,UNIQUE(pool_id, node_id))")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_cluster_members_pool "
        "ON cluster_members(pool_id, enabled)")


async def _migration_009_custom_skills(db: aiosqlite.Connection) -> None:
    """管理员自定义对话技能：名称、说明、提示词和启停。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS custom_skills ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL UNIQUE,"
        "hint TEXT NOT NULL DEFAULT '',"
        "icon TEXT NOT NULL DEFAULT 'spark',"
        "prompt TEXT NOT NULL,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "sort INTEGER NOT NULL DEFAULT 0,"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)")


async def _migration_010_org_quota(db: aiosqlite.Connection) -> None:
    """用户组、管理员角色与每用户 Token 配额。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS user_groups ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,"
        "description TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS admin_roles ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,"
        "permissions TEXT NOT NULL DEFAULT '[]',is_super INTEGER NOT NULL DEFAULT 0,"
        "created_at REAL NOT NULL)")
    await _add_column(db, "users", "group_id", "group_id INTEGER")
    await _add_column(db, "users", "admin_role_id", "admin_role_id INTEGER")
    await _add_column(db, "users", "daily_token_limit", "daily_token_limit INTEGER NOT NULL DEFAULT 0")
    await _add_column(db, "users", "monthly_token_limit", "monthly_token_limit INTEGER NOT NULL DEFAULT 0")


async def _migration_011_group_tree(db: aiosqlite.Connection) -> None:
    """用户组升级为部门树：上级部门、负责人和排序。"""
    await _add_column(db, "user_groups", "parent_id", "parent_id INTEGER")
    await _add_column(db, "user_groups", "leader_id", "leader_id INTEGER")
    await _add_column(db, "user_groups", "sort", "sort INTEGER NOT NULL DEFAULT 0")


async def _migration_012_content_safety(db: aiosqlite.Connection) -> None:
    """内容安全：敏感词库与命中记录。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS sensitive_words ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "word TEXT NOT NULL UNIQUE,"
        "category TEXT NOT NULL DEFAULT '',"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "note TEXT NOT NULL DEFAULT '',"
        "created_at REAL NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS moderation_hits ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER,"
        "username TEXT NOT NULL DEFAULT '',"
        "direction TEXT NOT NULL DEFAULT 'input',"
        "action TEXT NOT NULL DEFAULT 'warn',"
        "words TEXT NOT NULL DEFAULT '[]',"
        "snippet TEXT NOT NULL DEFAULT '',"
        "model TEXT NOT NULL DEFAULT '',"
        "conversation_id INTEGER,"
        "created_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_moderation_hits_time ON moderation_hits(created_at DESC)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_moderation_hits_user ON moderation_hits(user_id, created_at DESC)")


async def _migration_013_collaboration(db: aiosqlite.Connection) -> None:
    """协作套件：智能体、小队、公告、服务台和对话分享。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS agents ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL UNIQUE,"
        "description TEXT NOT NULL DEFAULT '',"
        "avatar TEXT NOT NULL DEFAULT '🤖',"
        "system_prompt TEXT NOT NULL DEFAULT '',"
        "model TEXT NOT NULL DEFAULT '',"
        "visibility TEXT NOT NULL DEFAULT 'public',"
        "owner_id INTEGER,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "sort INTEGER NOT NULL DEFAULT 0,"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)")
    await _add_column(db, "conversations", "agent_id", "agent_id INTEGER")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS squads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL UNIQUE,"
        "description TEXT NOT NULL DEFAULT '',"
        "owner_id INTEGER NOT NULL,"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS squad_members ("
        "squad_id INTEGER NOT NULL REFERENCES squads(id) ON DELETE CASCADE,"
        "user_id INTEGER NOT NULL,"
        "role TEXT NOT NULL DEFAULT 'member',"
        "joined_at REAL NOT NULL,"
        "PRIMARY KEY(squad_id,user_id))")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS squad_agents ("
        "squad_id INTEGER NOT NULL REFERENCES squads(id) ON DELETE CASCADE,"
        "agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,"
        "added_at REAL NOT NULL,"
        "PRIMARY KEY(squad_id,agent_id))")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS squad_conversations ("
        "squad_id INTEGER NOT NULL REFERENCES squads(id) ON DELETE CASCADE,"
        "conversation_id INTEGER NOT NULL,"
        "shared_by INTEGER NOT NULL,"
        "created_at REAL NOT NULL,"
        "PRIMARY KEY(squad_id,conversation_id))")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS announcements ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "title TEXT NOT NULL,"
        "content TEXT NOT NULL,"
        "level TEXT NOT NULL DEFAULT 'info',"
        "pinned INTEGER NOT NULL DEFAULT 0,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "created_by INTEGER,"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS tickets ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "username TEXT NOT NULL DEFAULT '',"
        "title TEXT NOT NULL,"
        "content TEXT NOT NULL,"
        "category TEXT NOT NULL DEFAULT 'other',"
        "priority TEXT NOT NULL DEFAULT 'normal',"
        "status TEXT NOT NULL DEFAULT 'open',"
        "assignee_id INTEGER,"
        "assignee_name TEXT NOT NULL DEFAULT '',"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL,"
        "last_reply_at REAL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS ticket_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,"
        "user_id INTEGER,"
        "username TEXT NOT NULL DEFAULT '',"
        "role TEXT NOT NULL DEFAULT 'user',"
        "content TEXT NOT NULL,"
        "created_at REAL NOT NULL)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS conversation_shares ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "conversation_id INTEGER NOT NULL,"
        "owner_id INTEGER NOT NULL,"
        "owner_name TEXT NOT NULL DEFAULT '',"
        "title TEXT NOT NULL DEFAULT '',"
        "token TEXT NOT NULL UNIQUE,"
        "visibility TEXT NOT NULL DEFAULT 'public',"
        "squad_id INTEGER,"
        "snapshot TEXT NOT NULL DEFAULT '[]',"
        "expires_at REAL,"
        "view_count INTEGER NOT NULL DEFAULT 0,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "created_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_enabled ON agents(enabled, sort)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_squad_members_user ON squad_members(user_id)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, updated_at DESC)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket ON ticket_messages(ticket_id, id)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_shares_owner ON conversation_shares(owner_id, created_at DESC)")


async def _migration_014_generated_files(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS generated_files("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "conversation_id INTEGER,"
        "message_id INTEGER,"
        "name TEXT NOT NULL,"
        "stored_name TEXT NOT NULL,"
        "mime TEXT NOT NULL DEFAULT '',"
        "size INTEGER NOT NULL DEFAULT 0,"
        "kind TEXT NOT NULL DEFAULT '',"
        "created_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_files_user "
        "ON generated_files(user_id, created_at DESC)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_files_conv "
        "ON generated_files(conversation_id, created_at DESC)")


async def _migration_015_workbench_tasks(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS scheduled_tasks("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "title TEXT NOT NULL,"
        "prompt TEXT NOT NULL,"
        "frequency TEXT NOT NULL DEFAULT 'once',"   # once | daily | weekly | monthly
        "run_at REAL,"
        "time_of_day TEXT NOT NULL DEFAULT '09:00',"
        "weekdays TEXT NOT NULL DEFAULT '',"        # 1=周一 ... 7=周日，逗号分隔
        "day_of_month INTEGER NOT NULL DEFAULT 1,"
        "model TEXT,"
        "agent_id INTEGER,"
        "output_format TEXT,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "next_run_at REAL,"
        "last_run_at REAL,"
        "last_status TEXT,"
        "last_result TEXT,"
        "last_conversation_id INTEGER,"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user "
        "ON scheduled_tasks(user_id, created_at DESC)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due "
        "ON scheduled_tasks(enabled, next_run_at)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS task_runs("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "task_id INTEGER NOT NULL,"
        "user_id INTEGER NOT NULL,"
        "trigger TEXT NOT NULL DEFAULT 'schedule',"
        "status TEXT NOT NULL DEFAULT 'running',"
        "started_at REAL NOT NULL,"
        "finished_at REAL,"
        "conversation_id INTEGER,"
        "summary TEXT,"
        "error TEXT)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id, id DESC)")


async def _migration_016_task_web(db: aiosqlite.Connection) -> None:
    """定时任务可选联网检索。"""
    await db.execute("ALTER TABLE scheduled_tasks ADD COLUMN web_enabled INTEGER NOT NULL DEFAULT 0")


async def _migration_017_workbench_templates(db: aiosqlite.Connection) -> None:
    """自定义工作台与工作台分享快照。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS workbench_templates("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "name TEXT NOT NULL,"
        "icon TEXT NOT NULL DEFAULT '🧩',"
        "description TEXT NOT NULL DEFAULT '',"
        "quick_json TEXT NOT NULL DEFAULT '[]',"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_workbench_templates_user "
        "ON workbench_templates(user_id, updated_at DESC)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS workbench_shares("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "owner_id INTEGER NOT NULL,"
        "owner_name TEXT NOT NULL DEFAULT '',"
        "title TEXT NOT NULL,"
        "icon TEXT NOT NULL DEFAULT '🧩',"
        "description TEXT NOT NULL DEFAULT '',"
        "quick_json TEXT NOT NULL DEFAULT '[]',"
        "token TEXT NOT NULL UNIQUE,"
        "expires_at REAL,"
        "view_count INTEGER NOT NULL DEFAULT 0,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "created_at REAL NOT NULL)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_workbench_shares_owner "
        "ON workbench_shares(owner_id, created_at DESC)")


async def _migration_018_workbench_capabilities(db: aiosqlite.Connection) -> None:
    """工作台可携带默认技能与插件；分享快照同步保存。"""
    await db.execute(
        "ALTER TABLE workbench_templates ADD COLUMN skill_id TEXT NOT NULL DEFAULT ''")
    await db.execute(
        "ALTER TABLE workbench_templates ADD COLUMN plugins_json TEXT NOT NULL DEFAULT '[]'")
    await db.execute(
        "ALTER TABLE workbench_shares ADD COLUMN skill_id TEXT NOT NULL DEFAULT ''")
    await db.execute(
        "ALTER TABLE workbench_shares ADD COLUMN plugins_json TEXT NOT NULL DEFAULT '[]'")


async def _migration_019_workbench_multi_skills(db: aiosqlite.Connection) -> None:
    """工作台可携带多个技能；当前使用的工作台按用户独立保存。"""
    await db.execute(
        "ALTER TABLE workbench_templates ADD COLUMN skills_json TEXT NOT NULL DEFAULT '[]'")
    await db.execute(
        "ALTER TABLE workbench_shares ADD COLUMN skills_json TEXT NOT NULL DEFAULT '[]'")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS workbench_active("
        "user_id INTEGER PRIMARY KEY,"
        "template_key TEXT NOT NULL DEFAULT '',"
        "updated_at REAL NOT NULL)")


async def _migration_021_generated_file_expiry(db: aiosqlite.Connection) -> None:
    """生成文档保留策略：记录到期时间与物理文件清理时间，供自动删除和提醒。"""
    await db.execute(
        "ALTER TABLE generated_files ADD COLUMN expires_at REAL NOT NULL DEFAULT 0")
    await db.execute(
        "ALTER TABLE generated_files ADD COLUMN deleted_at REAL NOT NULL DEFAULT 0")
    # 旧文件没有到期时间，按默认 30 天回填；为避免升级时立刻删除历史文件，
    # 至少给旧文件从升级时刻起 30 天的过渡期。
    now = time.time()
    grace = now + 30 * 86400
    await db.execute(
        "UPDATE generated_files SET expires_at="
        "CASE WHEN created_at+? > ? THEN created_at+? ELSE ? END "
        "WHERE expires_at=0",
        (30 * 86400, grace, 30 * 86400, grace))
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_files_expiry "
        "ON generated_files(deleted_at, expires_at)")


async def _migration_020_upload_parse_state(db: aiosqlite.Connection) -> None:
    """附件解析状态：记录解析时间、耗时和失败原因，供控制台重新解析。"""
    await db.execute(
        "ALTER TABLE uploads ADD COLUMN parsed_at REAL NOT NULL DEFAULT 0")
    await db.execute(
        "ALTER TABLE uploads ADD COLUMN parse_ms INTEGER NOT NULL DEFAULT 0")
    await db.execute(
        "ALTER TABLE uploads ADD COLUMN parse_error TEXT NOT NULL DEFAULT ''")


async def _migration_022_prompt_center(db: aiosqlite.Connection) -> None:
    """提示词中心：给已有模板表补管理元数据，并记录默认内容和修订信息。"""
    for column, ddl in (
        ("name", "name TEXT NOT NULL DEFAULT ''"),
        ("description", "description TEXT NOT NULL DEFAULT ''"),
        ("kind", "kind TEXT NOT NULL DEFAULT 'core'"),
        ("source", "source TEXT NOT NULL DEFAULT 'builtin'"),
        ("enabled", "enabled INTEGER NOT NULL DEFAULT 1"),
        ("sort", "sort INTEGER NOT NULL DEFAULT 0"),
        ("default_content", "default_content TEXT NOT NULL DEFAULT ''"),
        ("meta_json", "meta_json TEXT NOT NULL DEFAULT '{}'"),
        ("updated_at", "updated_at REAL NOT NULL DEFAULT 0"),
        ("updated_by", "updated_by TEXT NOT NULL DEFAULT ''"),
    ):
        await _add_column(db, "prompt_templates", column, ddl)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompt_templates_kind "
        "ON prompt_templates(kind, sort, id)")


async def _migration_023_front_features(db: aiosqlite.Connection) -> None:
    """前台功能开关与自定义图标库。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS front_features("
        "key TEXT PRIMARY KEY,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "icon_key TEXT NOT NULL DEFAULT '',"
        "icon_tone TEXT NOT NULL DEFAULT 'blue',"
        "icon_id INTEGER NOT NULL DEFAULT 0,"
        "updated_at REAL NOT NULL DEFAULT 0,"
        "updated_by TEXT NOT NULL DEFAULT '')")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS front_icons("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL,"
        "mime TEXT NOT NULL,"
        "data TEXT NOT NULL,"
        "created_at REAL NOT NULL,"
        "created_by TEXT NOT NULL DEFAULT '')")


async def _migration_024_task_agent(db: aiosqlite.Connection) -> None:
    """任务 Agent：任务档案、执行轨迹、自检结论与重试次数。"""
    await _add_column(db, "scheduled_tasks", "memory", "memory TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "scheduled_tasks", "goal", "goal TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "scheduled_tasks", "last_verdict",
                      "last_verdict TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "task_runs", "steps", "steps TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "task_runs", "verdict", "verdict TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "task_runs", "attempts", "attempts INTEGER NOT NULL DEFAULT 0")


async def _migration_025_task_p2(db: aiosqlite.Connection) -> None:
    """任务 Agent P2：触发方式（定时/事件/条件）、条件判断与结果投递。"""
    for column, ddl in (
        ("trigger_mode", "trigger_mode TEXT NOT NULL DEFAULT 'schedule'"),
        ("event_key", "event_key TEXT NOT NULL DEFAULT ''"),
        ("event_filter", "event_filter TEXT NOT NULL DEFAULT ''"),
        ("condition", "condition TEXT NOT NULL DEFAULT ''"),
        ("notify_channel", "notify_channel TEXT NOT NULL DEFAULT ''"),
        ("notify_url", "notify_url TEXT NOT NULL DEFAULT ''"),
        ("notify_format", "notify_format TEXT NOT NULL DEFAULT 'json'"),
        ("notify_on", "notify_on TEXT NOT NULL DEFAULT 'ok'"),
    ):
        await _add_column(db, "scheduled_tasks", column, ddl)
    await _add_column(db, "task_runs", "event", "event TEXT NOT NULL DEFAULT ''")
    await _add_column(db, "task_runs", "notified", "notified INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "model_columns_and_permissions", _migration_001_model_columns),
    (2, "chat_uploads", _migration_002_chat_uploads),
    (3, "long_term_memories", _migration_003_memories),
    (4, "personal_scope", _migration_004_personal_scope),
    (5, "kb_preferences", _migration_005_kb_preferences),
    (6, "library", _migration_006_library),
    (7, "library_folders_tags", _migration_007_library_folders_tags),
    (8, "cluster_pool", _migration_008_cluster),
    (9, "custom_skills", _migration_009_custom_skills),
    (10, "org_roles_quota", _migration_010_org_quota),
    (11, "group_tree", _migration_011_group_tree),
    (12, "content_safety", _migration_012_content_safety),
    (13, "collaboration", _migration_013_collaboration),
    (14, "generated_files", _migration_014_generated_files),
    (15, "workbench_tasks", _migration_015_workbench_tasks),
    (16, "task_web", _migration_016_task_web),
    (17, "workbench_templates", _migration_017_workbench_templates),
    (18, "workbench_capabilities", _migration_018_workbench_capabilities),
    (19, "workbench_multi_skills", _migration_019_workbench_multi_skills),
    (20, "upload_parse_state", _migration_020_upload_parse_state),
    (21, "generated_file_expiry", _migration_021_generated_file_expiry),
    (22, "prompt_center", _migration_022_prompt_center),
    (23, "front_features", _migration_023_front_features),
    (24, "task_agent_fields", _migration_024_task_agent),
    (25, "task_p2_triggers", _migration_025_task_p2),
]


async def apply_migrations(db: aiosqlite.Connection) -> list[int]:
    """按版本顺序执行迁移；已执行的版本不会重复跑。"""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations("
        "version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at REAL NOT NULL)")
    await db.commit()
    cur = await db.execute("SELECT version FROM schema_migrations")
    applied = {int(r["version"]) for r in await cur.fetchall()}
    done: list[int] = []
    for version, name, fn in MIGRATIONS:
        if version in applied:
            continue
        await fn(db)
        await db.execute(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
            (version, name, time.time()),
        )
        await db.commit()
        done.append(version)
    return done


async def init_db() -> None:
    db = await connect()
    try:
        await db.executescript(SCHEMA)
        try:
            await db.executescript(KB_SCHEMA)
        except Exception:
            pass  # 部分环境无 fts5，退化为 LIKE 检索
        await db.commit()
        await apply_migrations(db)
        # 补齐模型清单
        exists = await (await db.execute("SELECT COUNT(*) c FROM models")).fetchone()
        if not exists["c"]:
            for m in MODEL_SEED:
                await db.execute(
                    "INSERT OR IGNORE INTO models(key,alias,label,family,note,filename,total_bytes,repo,fit,sort) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (m["key"], m.get("alias", ""), m["label"], m["family"], m["note"], m["filename"],
                     m["total_bytes"], m["repo"], m["fit"], m["sort"]),
                )
            await db.commit()
        # 扩展分类模型只补一次；用户删掉的条目不会在每次启动时重新出现
        flag = await (await db.execute(
            "SELECT value FROM settings WHERE key='model_catalog_extras'")).fetchone()
        if not flag:
            for m in MODEL_CATALOG_EXTRAS:
                await db.execute(
                    "INSERT OR IGNORE INTO models(key,alias,label,family,note,filename,total_bytes,repo,fit,sort,"
                    "category,engine,homepage,installable) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m["key"], m.get("alias", ""), m["label"], m["family"], m["note"], m["filename"],
                     m["total_bytes"], m["repo"], m.get("fit", "unknown"), m.get("sort", 0),
                     m.get("category", "text"), m.get("engine", "llama.cpp"),
                     m.get("homepage", ""), int(m.get("installable", 1))),
                )
            await db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('model_catalog_extras','v2')")
            await db.commit()
        # Ollama 常用模型也补进内置清单；独立标记，老库升级时只补这一次
        flag_ollama = await (await db.execute(
            "SELECT value FROM settings WHERE key='model_catalog_ollama'")).fetchone()
        if not flag_ollama or str(flag_ollama["value"]) != "v2":
            for m in OLLAMA_MODEL_CATALOG:
                await db.execute(
                    "INSERT OR IGNORE INTO models(key,alias,label,family,note,filename,total_bytes,repo,fit,sort,"
                    "category,engine,homepage,installable) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m["key"], m.get("alias", ""), m["label"], m["family"], m["note"], m["filename"],
                     m["total_bytes"], m["repo"], m.get("fit", "unknown"), m.get("sort", 0),
                     m.get("category", "text"), m.get("engine", "Ollama"),
                     m.get("homepage", ""), int(m.get("installable", 0))),
                )
            await db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('model_catalog_ollama','v2')")
            await db.commit()
        # 修正独立引擎名称；每次启动都校正，兼容已升级的旧库
        for key, engine in ENGINE_REQUIREMENTS.items():
            await db.execute(
                "UPDATE models SET engine=? WHERE key=? AND installable=0",
                (engine, key),
            )
        await db.commit()
        await db.execute(
            "INSERT OR IGNORE INTO auth_identities(user_id,provider,provider_uid,display_name,created_at) "
            "SELECT id,'username',lower(username),username,created_at FROM users"
        )
        await db.commit()
        for key, alias in {'1.5b': 'deepseek-r1-1.5b', '7b': 'deepseek-r1-7b', '14b': 'deepseek-r1-14b', '32b': 'deepseek-r1-32b', 'qwen3-8b': 'deepseek-r1-0528-8b', 'llama-8b': 'deepseek-r1-llama-8b', 'llama-70b': 'deepseek-r1-llama-70b', 'v4-flash': 'deepseek-v4-flash'}.items():
            await db.execute("UPDATE models SET alias=? WHERE key=? AND (alias IS NULL OR alias='')", (alias, key))
        await db.commit()
    finally:
        await db.close()


async def fetch_all(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    async with _shared_guard():
        db = await _shared_connection()
        cur = await db.execute(sql, tuple(params))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def fetch_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = await fetch_all(sql, params)
    return rows[0] if rows else None


async def execute(sql: str, params: Iterable[Any] = ()) -> int:
    async with _shared_guard():
        db = await _shared_connection()
        cur = await db.execute(sql, tuple(params))
        await db.commit()
        return cur.lastrowid or 0


async def executemany(sql: str, seq: list[tuple]) -> None:
    async with _shared_guard():
        db = await _shared_connection()
        await db.executemany(sql, list(seq))
        await db.commit()


async def get_setting(key: str, default: str | None = None) -> str | None:
    row = await fetch_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


async def audit(user: dict | None, action: str, target: str = "", detail: str = "",
                status: str = "ok", ip: str = "") -> None:
    await execute(
        "INSERT INTO audit_logs(ts,user_id,username,action,target,detail,status,ip) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (time.time(), (user or {}).get("id"), (user or {}).get("username", "anonymous"),
         action, target, detail[:2000], status, ip),
    )


def parse_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}
