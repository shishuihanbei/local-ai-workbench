"""本地部署平台：llama.cpp 由工作台管理，其余平台按地址探测是否已启动。

这里只做“平台注册 + 状态探测 + 配置保存”，不替用户安装第三方平台。
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from . import hardware, llama

PLATFORMS: dict[str, dict[str, Any]] = {
    "llama.cpp": {
        "name": "llama.cpp",
        "kind": "managed",
        "default_base": "",
        "probe": "",
        "installable": True,
        "multimodal": "",
        "model_types": ["文字 / 对话", "代码 / 编程"],
        "homepage": "https://github.com/ggml-org/llama.cpp",
        "note": "工作台内置，可一键安装、启动和切换 GGUF 模型；视觉模型需要 mmproj，当前未接入",
    },
    "ollama": {
        "name": "Ollama",
        "kind": "external",
        "default_base": "http://127.0.0.1:11434",
        "probe": "/api/tags",
        "installable": True,
        "multimodal": "多模态（部分）",
        "model_types": ["文字 / 对话", "代码 / 编程", "多模态 / 视觉（部分）", "向量 / 检索（部分）"],
        "homepage": "https://ollama.com/download",
        "note": "便携版程序装在 platforms/ollama，模型统一在 models/ollama；pull 下来的模型会出现在「模型」页下拉，不需要 llama.cpp",
    },
    "vllm": {
        "name": "vLLM",
        "kind": "external",
        "default_base": "http://127.0.0.1:8000",
        "probe": "/v1/models",
        "installable": True,
        "multimodal": "多模态",
        "model_types": ["文字 / 对话", "代码 / 编程", "多模态 / 视觉", "向量 / 检索（部分）"],
        "homepage": "https://docs.vllm.ai/",
        "note": "Linux 上装进 platforms\\vllm\\.venv（独立环境，不污染工作台依赖）；Windows 官方不支持，卡片给 WSL2 / Docker 命令",
    },
    "lmstudio": {
        "name": "LM Studio",
        "kind": "external",
        "default_base": "http://127.0.0.1:1234",
        "probe": "/v1/models",
        "installable": True,
        "multimodal": "多模态（部分）",
        "model_types": ["文字 / 对话", "代码 / 编程", "多模态 / 视觉（部分）"],
        "homepage": "https://lmstudio.ai/",
        "note": "一键装的是无界面版 llmster：程序和模型都在 platforms\\lmstudio，不用开桌面客户端；已装的桌面版也能识别",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容",
        "kind": "external",
        "default_base": "http://127.0.0.1:8001",
        "probe": "/v1/models",
        "installable": False,
        "multimodal": "多模态看服务",
        "model_types": ["取决于所接服务", "通常文字 / 代码", "多模态看接口"],
        "homepage": "",
        "note": "任意兼容 /v1/models 与 /v1/chat/completions 的服务；工作台不会安装它，需先在外部启动",
    },
}

DEFAULT_SELECTED = ["llama.cpp"]


def normalize_selected(value: Any) -> list[str]:
    """只接受已知平台；空选择回到默认 llama.cpp。"""
    if not isinstance(value, list):
        return list(DEFAULT_SELECTED)
    keys = [str(v) for v in value if str(v) in PLATFORMS]
    return keys or list(DEFAULT_SELECTED)


def endpoints(cfg: dict) -> dict[str, str]:
    raw = cfg.get("platform_endpoints")
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for key, meta in PLATFORMS.items():
        if key == "llama.cpp":
            continue
        value = str(raw.get(key) or "").strip()
        out[key] = value or str(meta["default_base"])
    return out


def clean_endpoints(value: Any, cfg: dict) -> dict[str, str]:
    """保存外部平台地址；没写协议时自动补 http://。"""
    current = endpoints(cfg)
    if not isinstance(value, dict):
        return current
    out = dict(current)
    for key in PLATFORMS:
        if key == "llama.cpp" or key not in value:
            continue
        url = str(value.get(key) or "").strip()[:300]
        if not url:
            out[key] = str(PLATFORMS[key]["default_base"])
        elif not url.startswith(("http://", "https://")):
            url = "http://" + url
        out[key] = url.rstrip("/")
    return out


def _port_open(base: str, timeout: float = 0.25) -> bool:
    """先做一次 TCP 连通性检查。Windows 上连接本机关闭端口会静默等到超时，
    直接发 HTTP 会让控制台白等 1 秒；这里 0.15 秒就能判断出没起。"""
    try:
        from urllib.parse import urlparse
        import socket
        p = urlparse(base if "://" in base else "http://" + base)
        host = p.hostname or "127.0.0.1"
        port = p.port or (443 if p.scheme == "https" else 80)
        local = host in ("127.0.0.1", "localhost", "0.0.0.0")
        s = socket.socket()
        s.settimeout(0.15 if local else timeout)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False
        finally:
            s.close()
    except Exception:
        return False


async def _probe_external(base: str, path: str, timeout: float = 0.6) -> tuple[bool, list[str], str]:
    if not base:
        return False, [], "没有填写服务地址"
    url = base.rstrip("/") + path
    try:
        if not await asyncio.to_thread(_port_open, base):
            return False, [], "未连接：端口未开放"
        # 本机服务正常时几十毫秒就回；超时说明没起或地址不通，不能拖住整个控制台
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return False, [], f"HTTP {resp.status_code}"
        payload = resp.json()
        rows = payload.get("models") if isinstance(payload, dict) else None
        if rows is None and isinstance(payload, dict):
            rows = payload.get("data")
        names: list[str] = []
        for row in rows or []:
            if isinstance(row, dict):
                names.append(str(row.get("name") or row.get("id") or ""))
            elif isinstance(row, str):
                names.append(row)
        names = [n for n in names if n]
        return True, names[:8], f"已连接 · {len(names)} 个模型"
    except Exception as exc:
        return False, [], f"未连接：{type(exc).__name__}"


def suitability(key: str, prof: dict) -> dict:
    """按本机 CPU/内存/显存/磁盘给平台一个是否适合安装的标签。"""
    ram = float(prof.get("ram_total_gb") or 0)
    disks = prof.get("disks") or []
    disk = float(disks[0].get("free_gb") or 0) if disks else 0
    gpus = prof.get("gpus") or []
    vram = max((float(g.get("vram_mb") or 0) / 1024 for g in gpus), default=0)
    gpu_name = str(gpus[0].get("name") or "") if gpus else ""

    if key == "llama.cpp":
        if ram < 4:
            return {"level": "bad", "label": "不适合", "text": f"内存只有 {ram:.0f}GB，CPU 推理也很吃力"}
        if ram < 8:
            return {"level": "warn", "label": "勉强", "text": f"内存 {ram:.0f}GB，只建议跑 1.5B/2B 小模型"}
        if disk and disk < 5:
            return {"level": "warn", "label": "勉强", "text": f"内存 {ram:.0f}GB 够用，但模型盘只剩 {disk:.0f}GB"}
        if vram >= 6:
            gpu = f"，{gpu_name} 约 {vram:.0f}GB 显存可尝试 GPU 加速"
        elif vram:
            gpu = f"，{gpu_name} 显存仅 {vram:.0f}GB，建议 CPU 推理"
        else:
            gpu = "，无独显时走 CPU"
        return {"level": "good", "label": "适合", "text": f"内存 {ram:.0f}GB{gpu}"}

    if key == "ollama":
        if ram < 4 or (disk and disk < 5):
            return {"level": "bad", "label": "不适合", "text": f"内存 {ram:.0f}GB、模型盘 {disk:.0f}GB，容量偏小"}
        if ram < 8:
            return {"level": "warn", "label": "勉强", "text": f"内存 {ram:.0f}GB，建议只拉小参数模型"}
        return {"level": "good", "label": "适合", "text": f"内存 {ram:.0f}GB，常驻服务空间充足"}

    if key == "vllm":
        if not gpus:
            return {"level": "bad", "label": "不适合", "text": "vLLM 需要 NVIDIA GPU，本机未检测到 NVIDIA 显卡"}
        if vram < 6:
            return {"level": "bad", "label": "不适合",
                    "text": f"检测到 {gpu_name} 约 {vram:.0f}GB 显存，低于 6GB 最低要求"}
        if vram < 8:
            return {"level": "warn", "label": "勉强", "text": f"显存约 {vram:.0f}GB，只能跑很小的模型"}
        if ram < 16:
            return {"level": "warn", "label": "勉强", "text": f"显存 {vram:.0f}GB 可用，但系统内存只有 {ram:.0f}GB"}
        return {"level": "good", "label": "适合", "text": f"{gpu_name} 约 {vram:.0f}GB 显存，可跑 7B 级模型"}

    if key == "lmstudio":
        os_name = str(prof.get("os") or "").lower()
        if not any(x in os_name for x in ("windows", "mac", "darwin")):
            return {"level": "unknown", "label": "需确认", "text": "LM Studio 主要面向 Windows/macOS，当前系统请先确认支持"}
        if ram < 4:
            return {"level": "bad", "label": "不适合", "text": f"内存只有 {ram:.0f}GB，桌面端运行空间不足"}
        if prof.get("avx2") is False and not any(x in os_name for x in ("arm64", "aarch64")):
            return {"level": "bad", "label": "不适合",
                    "text": "CPU 不支持 AVX2：LM Studio 0.0.27 的 lms 启动会直接非法指令退出"}
        if ram < 8:
            return {"level": "warn", "label": "勉强", "text": f"内存 {ram:.0f}GB，建议只加载小模型"}
        return {"level": "good", "label": "适合", "text": f"桌面端可用，内存 {ram:.0f}GB"}

    return {"level": "unknown", "label": "需确认",
            "text": "取决于你接入的服务本身，工作台不做硬件判断"}


async def status(cfg: dict, selected: list[str] | None = None,
                 llama_status: dict | None = None, probe_all: bool = False) -> list[dict]:
    """探测平台；probe_all=True 时连未勾选的平台也扫描，用于“更新”发现新平台。"""
    selected = normalize_selected(selected if selected is not None else cfg.get("deploy_platforms"))
    prof_task = asyncio.to_thread(hardware.profile)
    eps = endpoints(cfg)
    tasks = {}
    for key, meta in PLATFORMS.items():
        if key != "llama.cpp" and (probe_all or key in selected):
            # Ollama 刚 pull 完可能短暂忙/慢，0.6 秒会把“已拉取”误判成未连接；
            # 本机服务给 2.5 秒，其余外部平台保持快速失败。
            timeout = 2.5 if key == "ollama" else 0.6
            tasks[key] = _probe_external(eps[key], str(meta["probe"]), timeout=timeout)
    # llama.cpp 的端口探测和外部平台、硬件画像并行，整体只等最慢的一个
    llama_task = None if llama_status is not None else llama.server.status()
    gathered = await asyncio.gather(prof_task, *tasks.values(),
                                    *([llama_task] if llama_task else []))
    prof = gathered[0]
    extras = gathered[1:]
    if llama_task:
        srv = extras[-1]
        probed = dict(zip(tasks.keys(), extras[:-1]))
    else:
        srv = llama_status or {}
        probed = dict(zip(tasks.keys(), extras))

    items: list[dict] = []
    for key, meta in PLATFORMS.items():
        item = {
            "key": key,
            "name": meta["name"],
            "kind": meta["kind"],
            "note": meta["note"],
            "homepage": meta["homepage"],
            "installable": bool(meta["installable"]),
            "multimodal": str(meta.get("multimodal") or ""),
            "selected": key in selected,
            "editable": key != "llama.cpp",
            "base_url": eps.get(key, ""),
            "model_types": list(meta.get("model_types") or []),
            "suitability": suitability(key, prof),
            "healthy": False,
            "running": False,
            "models": [],
            "detail": "",
        }
        if key == "llama.cpp":
            installed = bool(hardware.llama_info()["installed"])
            item["installed"] = installed
            item["healthy"] = bool(srv.get("healthy"))
            item["running"] = bool(srv.get("running"))
            item["models"] = list(srv.get("served") or [])
            if srv.get("error"):
                item["detail"] = str(srv["error"])
            elif srv.get("healthy"):
                item["detail"] = f"运行中 · 端口 {srv.get('port', 8080)}"
            elif installed:
                item["detail"] = "已安装，尚未启动"
            else:
                item["detail"] = "未安装，可一键安装"
        else:
            healthy, models, detail = probed.get(key, (False, [], "未选中，不检测"))
            item["healthy"] = healthy
            item["running"] = healthy
            item["models"] = models
            if healthy and key not in selected:
                detail = f"{detail}（未勾选）"
            item["detail"] = detail
            item["installed"] = None
        items.append(item)
    return items
