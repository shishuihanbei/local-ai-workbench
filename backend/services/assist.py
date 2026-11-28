"""云端补强：本地为主，云端只补最难的请求与本地失败。

设计原则：
- 默认不改变路由，只有明确命中规则才升级，避免“什么都往云端扔”。
- 敏感内容一律留在本地；附件默认不参与云端补强。
- 每日 Token 预算，超了自动回落本地。
- 每次云端调用都落库，便于审计成本与效果。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import httpx

from ..config import load_config
from ..db import execute, fetch_all, fetch_one
from .secrets_store import decrypt

_LOCAL_HOSTS = ("127.", "localhost", "0.0.0.0", "192.168.", "10.", "172.16.",
                "172.17.", "172.18.", "172.19.", "::1")
_SENSITIVE_WORDS = (
    "身份证", "银行卡", "密码", "私钥", "密钥", "api key", "apikey", "secret",
    "薪酬", "工资条", "病历", "诊断书", "体检报告", "客户名单", "合同金额", "报价单",
)
_SENSITIVE_RE = (
    re.compile(r"\b1[3-9]\d{9}\b"),                 # 手机号
    re.compile(r"\b\d{17}[\dXx]\b"),                # 身份证号
    re.compile(r"\b\d{16,19}\b"),                   # 银行卡/长编号
)
_MULTI_STEP = re.compile(r"先.{0,20}(再|然后|接着|最后)|分别|逐条|对比|"
                         r"分析.{0,10}(并|然后)|一步一步|分步骤")


def _is_local(base: str) -> bool:
    text = str(base or "").lower()
    return (not text) or any(h in text for h in _LOCAL_HOSTS)


async def target(cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """选出用于补强的云端供应商；没有可用配置就返回 None。"""
    cfg = cfg or load_config()
    if not bool(cfg.get("assist_enabled", True)):
        return None
    rows = await fetch_all("SELECT * FROM providers WHERE enabled=1 ORDER BY id")
    if not rows:
        return None
    pid = int(cfg.get("assist_provider_id") or 0)
    chosen = None
    if pid:
        chosen = next((p for p in rows if int(p["id"]) == pid), None)
    if not chosen:
        clouds = [p for p in rows if not _is_local(p.get("base_url") or "")]
        # 优先名字里带豆包/火山的供应商，其次第一个云端供应商。
        chosen = next((p for p in clouds
                       if any(k in str(p.get("name") or "").lower()
                              for k in ("豆包", "doubao", "火山", "ark", "volces"))), None)
        chosen = chosen or (clouds[0] if clouds else None)
    if not chosen or _is_local(chosen.get("base_url") or ""):
        return None
    model = str(cfg.get("assist_model") or "").strip()
    if not model:
        models = [m.strip() for m in str(chosen.get("models") or "").split(",") if m.strip()]
        model = models[0] if models else ""
    if not model:
        return None
    try:
        key = decrypt(chosen.get("api_key") or "")
    except Exception:
        key = ""
    return {
        "provider": str(chosen.get("name") or "cloud"),
        "provider_id": int(chosen["id"]),
        "base": str(chosen.get("base_url") or "").rstrip("/"),
        "key": key,
        "model": model,
        "price_in": float(chosen.get("price_in") or 0),
        "price_out": float(chosen.get("price_out") or 0),
    }


async def is_assist_model(model: str) -> bool:
    t = await target()
    return bool(t and str(model or "").strip() == t["model"])


def decision(t: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "provider": t["provider"], "provider_id": t["provider_id"],
        "base": t["base"], "key": t["key"], "model": t["model"],
        "strategy": "assist", "reason": reason, "route_id": None,
        "fallback": [], "price_in": t["price_in"], "price_out": t["price_out"],
        "assist": True,
    }


def sensitivity(text: str, cfg: dict[str, Any] | None = None) -> str:
    """命中敏感信息就返回原因，空字符串表示可以上云。"""
    cfg = cfg or load_config()
    body = str(text or "")
    low = body.lower()
    words = list(_SENSITIVE_WORDS) + [
        w.strip().lower() for w in str(cfg.get("assist_sensitive_words") or "").split(",")
        if w.strip()
    ]
    for w in words:
        if w and w in low:
            return f"命中敏感词「{w}」，仅本地处理"
    for rx in _SENSITIVE_RE:
        if rx.search(body):
            return "疑似包含手机号/证件号/银行卡号，仅本地处理"
    return ""


def complexity(message: str, fmt: str = "", attachments: int = 0) -> int:
    text = str(message or "")
    score = 0
    if fmt:
        score += 2
    if len(text) >= 1200:
        score += 2
    elif len(text) >= 600:
        score += 1
    if _MULTI_STEP.search(text):
        score += 1
    if attachments >= 3:
        score += 1
    return score


def estimate_tokens(text: str) -> int:
    return max(1, int(len(str(text or ""))) // 2 + 256)


async def used_today(user_id: int) -> int:
    since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    row = await fetch_one(
        "SELECT COALESCE(SUM(tokens_in+tokens_out),0) n FROM assist_logs "
        "WHERE user_id=? AND created_at>=?", (int(user_id), since)) or {}
    return int(row.get("n") or 0)


async def budget_ok(user_id: int, chars: int, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_config()
    limit = int(cfg.get("assist_daily_tokens") or 0)
    if limit <= 0:
        return True
    return await used_today(user_id) + (int(chars or 0) // 2 + 256) < limit


async def log(*, user_id: int, provider: str, model: str, reason: str,
              conversation_id: int | None = None, task_id: int | None = None,
              prompt_chars: int = 0, tokens_in: int = 0, tokens_out: int = 0,
              latency_ms: int = 0, status: str = "ok", error: str = "") -> None:
    try:
        await execute(
            "INSERT INTO assist_logs(user_id,conversation_id,task_id,provider,model,reason,"
            "prompt_chars,tokens_in,tokens_out,latency_ms,status,error,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (int(user_id), conversation_id, task_id, provider, model, reason,
             int(prompt_chars), int(tokens_in), int(tokens_out), int(latency_ms),
             status, str(error or "")[:300], time.time()))
    except Exception:
        pass


async def complete(t: dict[str, Any], messages: list[dict[str, Any]],
                   params: dict[str, Any]) -> dict[str, Any]:
    """非流式调用云端；只用于本地失败后的兜底，避免两条流式解析逻辑。"""
    payload = {
        "model": t["model"], "messages": messages, "stream": False,
        "temperature": params.get("temperature", 0.7),
        "max_tokens": params.get("max_tokens") or 2048,
    }
    headers = {"Content-Type": "application/json"}
    if t.get("key"):
        headers["Authorization"] = f"Bearer {t['key']}"
    started = time.monotonic()
    timeout = httpx.Timeout(connect=10, read=120, write=20, pool=20)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{t['base']}/chat/completions", json=payload, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"云端补强返回 {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    content = str((choice.get("message") or {}).get("content") or "")
    usage = data.get("usage") or {}
    return {
        "content": content,
        "usage": usage,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "model": t["model"],
    }
