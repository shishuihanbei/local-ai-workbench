"""手机号 / 邮箱验证码：发送、限流与校验。

验证码只保存在进程内存里，5 分钟有效；重启后自动失效。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from ..config import secret_key
from . import auth_delivery, auth_providers

_CODES: dict[str, dict] = {}
_SENT: dict[str, list[float]] = {}
TTL = 300
MAX_ATTEMPTS = 5
SEND_GAP = 60
HOUR_MAX = 5


def normalize(channel: str, target: str) -> str:
    if channel == "phone":
        return auth_delivery.normalize_phone(target)
    return str(target or "").strip().lower()


def _key(channel: str, target: str) -> str:
    return f"{channel}:{target}"


def _hash(code: str) -> str:
    return hmac.new(secret_key().encode(), code.encode(), hashlib.sha256).hexdigest()


def _clean(now: float) -> None:
    for key, item in list(_CODES.items()):
        if item["expires"] < now:
            _CODES.pop(key, None)
    for key, ts in list(_SENT.items()):
        fresh = [t for t in ts if now - t < 3600]
        if fresh:
            _SENT[key] = fresh
        else:
            _SENT.pop(key, None)


def _rate_check(key: str, now: float) -> None:
    hist = _SENT.get(key, [])
    if hist and now - hist[-1] < SEND_GAP:
        wait = int(SEND_GAP - (now - hist[-1])) + 1
        raise ValueError(f"发送太频繁，请 {wait} 秒后再试")
    if len([t for t in hist if now - t < 3600]) >= HOUR_MAX:
        raise ValueError("这个号码/邮箱 1 小时内发送次数过多，请稍后再试")
    hist.append(now)
    _SENT[key] = hist


async def send(channel: str, target: str) -> dict:
    channel = str(channel or "").strip().lower()
    if channel not in ("phone", "email"):
        raise ValueError("channel 只能是 phone 或 email")
    target = normalize(channel, target)
    if channel == "phone" and not auth_delivery.PHONE_RE.fullmatch(target):
        raise ValueError("手机号格式不正确")
    if channel == "email" and not auth_delivery.EMAIL_RE.fullmatch(target):
        raise ValueError("邮箱格式不正确")
    cfg = auth_providers.provider_settings(channel)
    if not auth_providers.configured(channel, cfg):
        raise ValueError(f"{auth_providers.LABELS[channel]}登录尚未配置好，请联系管理员")
    now = time.time()
    _clean(now)
    key = _key(channel, target)
    _rate_check(key, now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    if channel == "phone":
        msg = await auth_delivery.send_sms(cfg, target, code)
    else:
        text = (f"你的登录验证码是 {code}。\n\n"
                "5 分钟内有效，请勿把验证码转发给他人。\n"
                "如果不是你本人操作，请忽略这封邮件。")
        msg = await auth_delivery.send_email(cfg, target, "登录验证码 · 本地 AI 工作台", text)
    _CODES[key] = {"hash": _hash(code), "expires": now + TTL, "attempts": 0, "sent": now}
    return {"ok": True, "msg": msg, "expires_in": TTL}


def verify(channel: str, target: str, code: str) -> tuple[bool, str]:
    channel = str(channel or "").strip().lower()
    target = normalize(channel, target)
    key = _key(channel, target)
    now = time.time()
    item = _CODES.get(key)
    if not item:
        return False, "验证码不存在或已过期，请重新获取"
    if item["expires"] < now:
        _CODES.pop(key, None)
        return False, "验证码已过期，请重新获取"
    expect = str(code or "").strip()
    if not re.fullmatch(r"\d{6}", expect):
        return False, "验证码应为 6 位数字"
    if item["attempts"] >= MAX_ATTEMPTS:
        _CODES.pop(key, None)
        return False, "验证码尝试次数过多，请重新获取"
    if not hmac.compare_digest(_hash(expect), item["hash"]):
        item["attempts"] += 1
        left = MAX_ATTEMPTS - item["attempts"]
        return False, f"验证码不正确，还可以尝试 {left} 次"
    _CODES.pop(key, None)
    return True, ""
