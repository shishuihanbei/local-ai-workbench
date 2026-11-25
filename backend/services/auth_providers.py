"""登录方式注册表与配置。

前期只启用「用户名 + 密码」；手机号、邮箱、QQ、微信的接口和配置位已经留好，
填好 data/auth_providers.json（或环境变量）后即可启用。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import quote

from ..config import DATA_DIR, secret_key
from .secrets_store import decrypt, encrypt, is_encrypted

CONFIG_PATH = DATA_DIR / "auth_providers.json"

PROVIDERS = ("username", "phone", "email", "qq", "wechat")

LABELS = {
    "username": "用户名",
    "phone": "手机号",
    "email": "邮箱",
    "qq": "QQ",
    "wechat": "微信",
}

MODES = {
    "username": "password",
    "phone": "otp",
    "email": "otp",
    "qq": "oauth",
    "wechat": "oauth",
}

SECRET_FIELDS = {
    "qq": ("client_secret",),
    "wechat": ("app_secret",),
    "phone": ("sms_key", "sms_secret"),
    "email": ("smtp_password",),
}


def _file_settings() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        raw = json.loads(CONFIG_PATH.read_text("utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return value.lower() in ("1", "true", "yes", "on")


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else None


def provider_settings(provider: str) -> dict:
    """读取单个登录方式的配置（含密钥，仅供后端使用）。"""
    base = dict(_file_settings().get(provider) or {})
    for key in SECRET_FIELDS.get(provider, ()):
        value = base.get(key)
        if value and is_encrypted(str(value)):
            try:
                base[key] = decrypt(str(value))
            except Exception:
                base[key] = ""
    prefix = "WORKBENCH_" + provider.upper() + "_"
    flag = _env_bool(prefix + "ENABLED")
    if flag is not None:
        base["enabled"] = flag
    field_map = {
        "client_id": "CLIENT_ID", "client_secret": "CLIENT_SECRET", "redirect_uri": "REDIRECT_URI",
        "app_id": "APP_ID", "app_secret": "APP_SECRET",
        "smtp_vendor": "SMTP_VENDOR", "smtp_host": "SMTP_HOST", "smtp_port": "SMTP_PORT",
        "smtp_user": "SMTP_USER", "smtp_password": "SMTP_PASSWORD", "smtp_from": "SMTP_FROM",
        "smtp_name": "SMTP_NAME", "smtp_ssl": "SMTP_SSL", "smtp_starttls": "SMTP_STARTTLS",
        "sms_vendor": "SMS_VENDOR", "sms_url": "SMS_URL", "sms_key": "SMS_KEY",
        "sms_secret": "SMS_SECRET", "sms_template": "SMS_TEMPLATE", "sms_sign": "SMS_SIGN",
        "sms_app_id": "SMS_APP_ID", "sms_region": "SMS_REGION", "sms_method": "SMS_METHOD",
        "sms_headers": "SMS_HEADERS", "sms_body": "SMS_BODY", "sms_success": "SMS_SUCCESS",
    }
    bool_fields = {"smtp_ssl", "smtp_starttls"}
    for key, env_name in field_map.items():
        value = _env(prefix + env_name)
        if value is not None:
            if key in bool_fields:
                base[key] = value.lower() in ("1", "true", "yes", "on")
            elif key == "smtp_port" and value.isdigit():
                base[key] = int(value)
            else:
                base[key] = value
    return base


def _sms_vendor(cfg: dict) -> str:
    return str(cfg.get("sms_vendor") or ("custom" if cfg.get("sms_url") else "aliyun"))


def configured(provider: str, settings: dict | None = None) -> bool:
    cfg = settings or provider_settings(provider)
    if provider == "username":
        return True
    if provider == "qq":
        return bool(cfg.get("client_id") and cfg.get("client_secret") and cfg.get("redirect_uri"))
    if provider == "wechat":
        return bool(cfg.get("app_id") and cfg.get("app_secret") and cfg.get("redirect_uri"))
    if provider == "email":
        return bool(cfg.get("smtp_host") and cfg.get("smtp_user")
                    and (cfg.get("smtp_from") or cfg.get("smtp_user")))
    if provider == "phone":
        vendor = _sms_vendor(cfg)
        if vendor == "aliyun":
            return bool(cfg.get("sms_key") and cfg.get("sms_secret")
                        and cfg.get("sms_sign") and cfg.get("sms_template"))
        if vendor == "tencent":
            return bool(cfg.get("sms_key") and cfg.get("sms_secret") and cfg.get("sms_app_id")
                        and cfg.get("sms_sign") and cfg.get("sms_template"))
        if vendor == "yunpian":
            return bool(cfg.get("sms_key") and cfg.get("sms_template"))
        if vendor == "custom":
            return bool(cfg.get("sms_url") and cfg.get("sms_body"))
        return False
    return False


def public_item(provider: str) -> dict:
    cfg = provider_settings(provider)
    ready = configured(provider, cfg)
    item = {
        "key": provider,
        "label": LABELS[provider],
        "login_mode": MODES[provider],
        "enabled": provider == "username" or bool(cfg.get("enabled")),
        "ready": ready,
    }
    if provider in ("qq", "wechat"):
        item["login_url"] = f"/api/auth/oauth/{provider}/start" if ready else None
    elif provider in ("phone", "email"):
        item["login_url"] = None
    if provider != "username" and not ready:
        if not cfg.get("enabled"):
            item["hint"] = "接口已预留，配置后启用"
        else:
            item["hint"] = "配置不完整，请检查密钥和回调地址"
    return item


def public_providers() -> list[dict]:
    return [public_item(p) for p in PROVIDERS]


def oauth_authorize_url(provider: str, state: str, fallback_redirect: str = "") -> str:
    cfg = provider_settings(provider)
    redirect_uri = str(cfg.get("redirect_uri") or fallback_redirect)
    if provider == "qq":
        return ("https://graph.qq.com/oauth2.0/authorize?response_type=code"
                f"&client_id={quote(str(cfg.get('client_id', '')))}"
                f"&redirect_uri={quote(redirect_uri, safe='')}"
                f"&state={quote(state)}&scope=get_user_info")
    if provider == "wechat":
        return ("https://open.weixin.qq.com/connect/qrconnect"
                f"?appid={quote(str(cfg.get('app_id', '')))}"
                f"&redirect_uri={quote(redirect_uri, safe='')}"
                "&response_type=code&scope=snsapi_login"
                f"&state={quote(state)}#wechat_redirect")
    raise ValueError("不支持的 OAuth 登录方式")


def make_state(provider: str) -> str:
    payload = f"{provider}.{int(time.time())}.{secrets.token_urlsafe(10)}"
    sig = hmac.new(secret_key().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode("utf-8")).decode("ascii").rstrip("=")


def verify_state(provider: str, state: str, max_age: int = 600) -> bool:
    if not state:
        return False
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        provider0, ts, nonce, sig = raw.split(".", 3)
        if provider0 != provider:
            return False
        if abs(time.time() - int(ts)) > max_age:
            return False
        expect = hmac.new(secret_key().encode("utf-8"),
                          f"{provider0}.{ts}.{nonce}".encode("utf-8"),
                          hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expect)
    except Exception:
        return False


def migrate_secrets() -> int:
    """把 auth_providers.json 里的明文密钥迁移为 AES-256-GCM 密文。"""
    data = _file_settings()
    changed = 0
    for provider, keys in SECRET_FIELDS.items():
        entry = data.get(provider)
        if not isinstance(entry, dict):
            continue
        for key in keys:
            value = entry.get(key)
            if value and not is_encrypted(str(value)):
                entry[key] = encrypt(str(value))
                changed += 1
    if changed:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(CONFIG_PATH)
    return changed
