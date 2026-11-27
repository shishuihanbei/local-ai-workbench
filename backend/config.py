"""全局配置：路径、运行时设置、跨平台常量。

优先级：环境变量 > data/config.json > 默认值
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent          # workbench/
DATA_DIR = Path(os.getenv("WORKBENCH_DATA") or BASE_DIR / "data")
LOG_DIR = DATA_DIR / "logs"
UPLOAD_DIR = DATA_DIR / "uploads"
AUDIO_DIR = DATA_DIR / "audio"
EXPORT_DIR = DATA_DIR / "exports"
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = DATA_DIR / "workbench.db"
CONFIG_PATH = DATA_DIR / "config.json"


def default_models_dir() -> Path:
    """模型目录：始终在程序根目录下，不写死某台机器的绝对路径。"""
    return BASE_DIR / "models"


def default_platforms_dir() -> Path:
    """下载的部署平台（llama.cpp 等）统一放在根目录 platforms 下。"""
    return BASE_DIR / "platforms"


def default_llama_dir() -> Path:
    return default_platforms_dir() / "llama.cpp"

for _d in (DATA_DIR, LOG_DIR, UPLOAD_DIR, AUDIO_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

DEFAULTS: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 9000,
    "models_dir": str(Path(os.getenv("WORKBENCH_MODELS") or default_models_dir())),
    "platforms_dir": str(Path(os.getenv("WORKBENCH_PLATFORMS") or default_platforms_dir())),
    "llama_dir": str(Path(os.getenv("WORKBENCH_LLAMA") or default_llama_dir())),
    "llama_bin": "",                 # 空 = 自动探测 <llama_dir>/llama-server(.exe)
    "hf_endpoint": os.getenv("WORKBENCH_HF_ENDPOINT") or "https://hf-mirror.com",
    "hf_token": os.getenv("HF_TOKEN") or "",   # 下载 gated 模型时可选
    "upstream_base": "http://127.0.0.1:8080/v1",
    "upstream_key": "sk-deepseek-local",
    "upstream_port": 8080,
    "ctx": 8192,
    "threads": 6,
    "gpu_layers": 0,
    "model": "",                     # 当前加载的模型 key
    "local_enabled": True,           # 管理员是否启用本地 llama.cpp 部署
    "deploy_platforms": ["llama.cpp"],  # 本地部署平台，可多选；空则默认 llama.cpp
    "platform_endpoints": {          # 外部平台地址（不带 /v1）
        "ollama": "http://127.0.0.1:11434",
        "vllm": "http://127.0.0.1:8000",
        "lmstudio": "http://127.0.0.1:1234",
        "custom": "http://127.0.0.1:8001",
    },
    "github_proxy": "auto",           # auto=自动换加速镜像；off=只用直连；也可填加速地址前缀
    "system_prompt": (
        "你是运行在用户本机内网上的助手，回答要准确、简洁，默认使用简体中文。"
    ),
    "kb_enabled": False,
    "kb_top_k": 3,
    "library_enabled": False,          # 总资料库默认关闭
    "library_max_chars": 12000,        # 一次对话最多带入的资料库正文字数
    "library_max_docs": 10,            # 一次对话最多选择 10 篇资料
    "memory_enabled": False,          # 长期记忆默认关闭：只用会话内上下文
    "memory_max_items": 40,           # 每个账号最多保留的记忆条数
    "memory_context_chars": 1200,     # 注入提示词的长期记忆字数上限
    "generated_file_retention_days": 30,  # 聊天生成的文档保留天数；到期自动删除
    "tts_voice": "zh-CN-XiaoxiaoNeural",
    "tunnel_target": "panel",        # panel | api | frontend
    "tunnel_token": "",
    "tunnel_domain": "",
    "frontend_url": "",                # 本地前端页面完整地址；空时按当前请求地址推导
    "log_level": "INFO",
    "session_hours": 72,
    "token_hours": 24,                     # Bearer 令牌有效期
    "cors_origins": "",                   # 前后端分离：允许的前端来源，逗号分隔；空=仅同源
    "serve_frontend": False,               # True 时后端兼做静态站点（单进程模式）
    "desktop_shortcuts": True,             # 首次启动在桌面放一个工作台图标
    "shortcut_mode": "lan",                # 图标打开的地址：local / lan / custom（默认局域网）
    "shortcut_lan_ip": "",                 # 选了 lan 时用哪个网卡地址
    "shortcut_custom_url": "",             # 选了 custom 时的 https/穿透地址
    "allow_register": False,
    "org_name": "本地 AI 工作台",
    "org_short_name": "AI 工作台",
    "org_domain": "",
    "org_industry": "",
    "org_size": "",
    "org_contact_name": "",
    "org_contact_email": "",
    "brand_logo": "",                                        # data/branding 下的 Logo 文件名
    "brand_tagline": "Local AI Workbench",
    "brand_login_title": "你的模型，\n只为你的账号工作。",
    "brand_login_lead": "本地模型、云端接口、知识库与调用记录统一在一处。登录后即可对话、生成自己的 API Key，并随时管理账号安全。",
    "brand_login_foot": "数据保存在你自己的机器上 · 不上传云端",
    "brand_auth_subtitle": "使用工作台账号继续对话",
    "brand_primary": "#4f6ef7",
    "brand_icp": "",
    "brand_icp_url": "https://beian.miit.gov.cn/",
    "brand_police": "",
    "brand_police_url": "https://beian.mps.gov.cn/#/query/webSearch",
    "brand_copyright": "",
    "watermark_enabled": False,
    "watermark_text": "{user} · {org} · 内部资料",
    "moderation_enabled": False,          # 内容安全总开关，默认关闭
    "moderation_input_action": "block",    # block | replace | warn
    "moderation_output_action": "replace",  # block | replace | warn
    "moderation_replace": "***",
    "moderation_min_chars": 1,            # 单词长度下限，避免单字误伤
    "websearch_enabled": True,           # 管理员总开关：关闭后网页检索和定时任务都不联网
    "websearch_max_sources": 5,          # 一次联网最多取多少条搜索结果
    "chat_max_active": 4,                # 同时进行的对话生成数，超出排队/拒绝
    "chat_rpm": 30,                      # 每账号每分钟最多发送消息条数
    "websearch_max_pages": 2,            # 最多抓取前几篇网页正文
}

_SECRET_FILE = DATA_DIR / "secret.key"


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text("utf-8")))
        except Exception:
            pass
    for key in list(DEFAULTS):
        env = os.getenv("WORKBENCH_" + key.upper())
        if env is not None and env != "":
            default = DEFAULTS[key]
            if isinstance(default, bool):
                cfg[key] = env.lower() in ("1", "true", "yes", "on")
            elif isinstance(default, int):
                try:
                    cfg[key] = int(env)
                except ValueError:
                    pass
            else:
                cfg[key] = env
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    data = {k: v for k, v in cfg.items() if k in DEFAULTS}
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def secret_key() -> str:
    """会话签名密钥，首次启动自动生成并落盘。"""
    if os.getenv("WORKBENCH_SECRET"):
        return os.environ["WORKBENCH_SECRET"]
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text("utf-8").strip()
    key = secrets.token_urlsafe(48)
    _SECRET_FILE.write_text(key, "utf-8")
    try:
        _SECRET_FILE.chmod(0o600)
    except Exception:
        pass
    return key


def llama_executable(cfg: dict[str, Any] | None = None) -> Path | None:
    cfg = cfg or load_config()
    if cfg.get("llama_bin"):
        p = Path(cfg["llama_bin"])
        return p if p.exists() else None
    d = Path(cfg["llama_dir"])
    for name in ("llama-server.exe", "llama-server"):
        p = d / name
        if p.exists():
            return p
    return None


def model_file_path(cfg: dict[str, Any], filename: str) -> Path:
    """cfg 可能是只带局部字段的副本（测试、临时配置），缺 models_dir 时回落默认目录。"""
    return Path(cfg.get("models_dir") or default_models_dir()) / filename
