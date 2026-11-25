"""登录方式的管理员配置：字段定义、教程、供应商预设与保存。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from . import auth_providers
from .secrets_store import encrypt

_LOCK = threading.Lock()

SECRET_KEYS = {
    "qq": ("client_secret",),
    "wechat": ("app_secret",),
    "phone": ("sms_key", "sms_secret"),
    "email": ("smtp_password",),
}

VENDOR_KEY = {"phone": "sms_vendor", "email": "smtp_vendor"}
DEFAULT_VENDOR = {"phone": "aliyun", "email": "qq"}


def F(key: str, label: str, type_: str = "text", placeholder: str = "", help_: str = "",
      options: list | None = None, default: str | bool | int = "", required: bool = False) -> dict:
    item = {"key": key, "label": label, "type": type_, "placeholder": placeholder,
            "help": help_, "required": required, "default": default}
    if options:
        item["options"] = options
    return item


QQ_FIELDS = [
    F("client_id", "App ID", placeholder="QQ 互联应用的 APP ID", required=True),
    F("client_secret", "App Key", "password", "QQ 互联应用的 APP Key", "只保存在本机，不回显原文", required=True),
    F("redirect_uri", "回调地址", placeholder="https://你的域名/api/auth/oauth/qq/callback",
      help_="控制台会按当前访问地址自动填入；必须和 QQ 互联后台填写的回调地址完全一致", required=True),
]

WECHAT_FIELDS = [
    F("app_id", "AppID", placeholder="微信开放平台网站应用的 AppID", required=True),
    F("app_secret", "AppSecret", "password", "微信开放平台网站应用的 AppSecret", "只保存在本机，不回显原文", required=True),
    F("redirect_uri", "回调地址", placeholder="https://你的域名/api/auth/oauth/wechat/callback",
      help_="控制台会按当前访问地址自动填入；必须落在微信后台登记的授权回调域内", required=True),
]

ALIYUN_FIELDS = [
    F("sms_key", "AccessKey ID", "password", "阿里云 RAM 用户的 AccessKey ID", required=True),
    F("sms_secret", "AccessKey Secret", "password", "阿里云 RAM 用户的 AccessKey Secret", "只保存在本机", required=True),
    F("sms_sign", "短信签名", placeholder="例如：某某科技", required=True),
    F("sms_template", "模板 CODE", placeholder="例如：SMS_123456789", required=True),
    F("sms_region", "地域", placeholder="cn-hangzhou", default="cn-hangzhou"),
]

TENCENT_FIELDS = [
    F("sms_key", "SecretId", "password", "腾讯云 API 密钥 SecretId", required=True),
    F("sms_secret", "SecretKey", "password", "腾讯云 API 密钥 SecretKey", "只保存在本机", required=True),
    F("sms_app_id", "SdkAppId", placeholder="短信应用的 SdkAppId", required=True),
    F("sms_sign", "短信签名", placeholder="例如：某某科技", required=True),
    F("sms_template", "模板 ID", placeholder="例如：1234567", required=True),
    F("sms_region", "地域", placeholder="ap-guangzhou", default="ap-guangzhou"),
]

YUNPIAN_FIELDS = [
    F("sms_key", "APIKEY", "password", "云片网 APIKEY", required=True),
    F("sms_sign", "短信签名", placeholder="例如：某某科技", help_="如果模板内容里已经带【签名】可留空"),
    F("sms_template", "短信内容", "textarea", "您的验证码是{code}，5分钟内有效。",
      "必须与云片后台审核通过的模板一致，用 {code} 表示验证码", required=True),
]

CUSTOM_SMS_FIELDS = [
    F("sms_url", "请求地址", placeholder="https://sms.example.com/api/send", required=True),
    F("sms_method", "请求方法", "select", options=["POST", "GET"], default="POST"),
    F("sms_headers", "请求头 JSON", "textarea", '{"Authorization":"Bearer xxx"}',
      "可选，JSON 对象；支持 {code}、{phone}、{sign} 占位符"),
    F("sms_body", "请求体模板", "textarea",
      '{"phone":"{phone}","code":"{code}","sign":"{sign}"}',
      "JSON 或表单文本，支持 {code}、{phone}、{sign}、{template} 占位符", required=True),
    F("sms_success", "成功标记", placeholder='例如："code":0 或 success',
      help_="可选；填写后响应正文必须包含该文本才视为发送成功"),
]

EMAIL_COMMON = [
    F("smtp_host", "SMTP 主机", placeholder="smtp.qq.com", required=True),
    F("smtp_port", "端口", "number", "465", default=465, required=True),
    F("smtp_ssl", "使用 SSL", "checkbox", default=True),
    F("smtp_starttls", "使用 STARTTLS", "checkbox", default=False),
    F("smtp_user", "SMTP 账号", placeholder="name@qq.com", required=True),
    F("smtp_password", "授权码 / 密码", "password", "邮箱授权码，不是网页登录密码", "只保存在本机", required=True),
    F("smtp_from", "发件地址", placeholder="name@qq.com", help_="通常与 SMTP 账号一致", required=True),
    F("smtp_name", "发件人名称", placeholder="AI 工作台", default="AI 工作台"),
]

PHONE_VENDORS = [
    {"key": "aliyun", "label": "阿里云短信", "description": "国内常用，需要签名和模板 CODE",
     "fields": ALIYUN_FIELDS},
    {"key": "tencent", "label": "腾讯云短信", "description": "需要 SdkAppId、签名和模板 ID",
     "fields": TENCENT_FIELDS},
    {"key": "yunpian", "label": "云片网", "description": "配置简单，使用审核通过的短信内容",
     "fields": YUNPIAN_FIELDS},
    {"key": "custom", "label": "自定义 / 其他短信平台", "description": "华为云、容联云、七牛云等不在内置列表的平台，用自定义 HTTP 接入",
     "fields": CUSTOM_SMS_FIELDS},
]

EMAIL_VENDORS = [
    {"key": "qq", "label": "QQ 邮箱", "description": "smtp.qq.com，使用邮箱设置里的授权码",
     "fields": [dict(f, default=465) if f["key"] == "smtp_port" else
                dict(f, default=True) if f["key"] == "smtp_ssl" else f for f in EMAIL_COMMON],
     "defaults": {"smtp_host": "smtp.qq.com", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False}},
    {"key": "163", "label": "网易 163 邮箱", "description": "smtp.163.com，使用客户端授权码",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.163.com", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False}},
    {"key": "gmail", "label": "Gmail", "description": "smtp.gmail.com，建议使用应用专用密码",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "aliyun", "label": "阿里云邮件推送", "description": "smtpdm.aliyun.com，按控制台给的发信地址配置",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtpdm.aliyun.com", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False}},
    {"key": "tencent", "label": "腾讯云邮件推送", "description": "smtp.qcloudmail.com",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.qcloudmail.com", "smtp_port": 465, "smtp_ssl": True, "smtp_starttls": False}},
    {"key": "sendgrid", "label": "SendGrid", "description": "用户名填 apikey，密码填 API Key",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.sendgrid.net", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "mailgun", "label": "Mailgun", "description": "smtp.mailgun.org，使用 SMTP 凭据",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.mailgun.org", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "outlook", "label": "Outlook / Microsoft 365", "description": "smtp.office365.com，需在邮箱后台开启 SMTP 认证",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "ses", "label": "Amazon SES", "description": "email-smtp.<地域>.amazonaws.com，使用 SES 的 SMTP 用户名和密码",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "email-smtp.us-east-1.amazonaws.com", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "postmark", "label": "Postmark", "description": "smtp.postmarkapp.com，用户名和密码都填 Server Token",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.postmarkapp.com", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "resend", "label": "Resend", "description": "smtp.resend.com，用户名填 resend，密码填 API Key",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "smtp.resend.com", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
    {"key": "custom", "label": "自定义 / 其他 SMTP", "description": "任何标准 SMTP 服务都能接入；不在列表里的服务商选这一项",
     "fields": EMAIL_COMMON,
     "defaults": {"smtp_host": "", "smtp_port": 587, "smtp_ssl": False, "smtp_starttls": True}},
]

GUIDES = {
    "qq": {
        "title": "QQ 扫码登录接入",
        "steps": [
            "打开 QQ 互联开放平台，注册开发者并创建“网站应用”。",
            "在应用里填写回调地址，必须与下面配置中的回调地址一字不差。",
            "把应用审核通过后拿到的 APP ID、APP Key 填进来。",
            "点“检查配置”，保存后启用，登录页就会出现 QQ 按钮。",
        ],
        "links": [{"label": "QQ 互联开放平台", "url": "https://connect.qq.com/"}],
        "note": "回调地址会按当前打开控制台的地址自动生成；给外网用时要换成公网域名并在开放平台同步登记。",
    },
    "wechat": {
        "title": "微信扫码登录接入",
        "steps": [
            "打开微信开放平台，创建“网站应用”并完成开发者资质认证。",
            "在应用详情里登记授权回调域，例如 127.0.0.1 或你的公网域名。",
            "复制 AppID、AppSecret 填入下面。",
            "回调地址必须落在已登记的回调域内，保存并启用后登录页出现微信按钮。",
        ],
        "links": [{"label": "微信开放平台", "url": "https://open.weixin.qq.com/"}],
        "note": "微信网站应用审核通常需要企业主体；个人可以先配置手机号/邮箱登录。",
    },
    "phone": {
        "title": "手机号验证码登录接入",
        "steps": [
            "选择短信供应商；国内推荐阿里云短信、腾讯云短信，小量测试可用云片网。",
            "在供应商控制台申请签名和验证码模板，模板变量名通常是 code。",
            "把密钥、签名、模板编号填进对应字段。",
            "点“发送测试”，收到短信后保存并启用。",
            "其他服务商可选“自定义 HTTP”，按服务商文档填请求地址、请求头和请求体。",
        ],
        "links": [
            {"label": "阿里云短信控制台", "url": "https://dysms.console.aliyun.com/"},
            {"label": "腾讯云短信控制台", "url": "https://console.cloud.tencent.com/smsv2"},
            {"label": "云片网", "url": "https://www.yunpian.com/"},
        ],
        "note": "短信按条计费；验证码 5 分钟有效，同一号码 60 秒内只能发一次。",
    },
    "email": {
        "title": "邮箱验证码登录接入",
        "steps": [
            "选择邮箱供应商，常见邮箱直接用 SMTP。",
            "QQ/163 邮箱要先在网页邮箱设置里开启 SMTP 并生成“授权码”，不要填网页登录密码。",
            "填写 SMTP 主机、端口、账号、授权码和发件地址。",
            "465 端口通常开 SSL；587 端口通常开 STARTTLS。",
            "点“发送测试”，收到邮件后保存并启用。",
        ],
        "links": [
            {"label": "QQ 邮箱设置", "url": "https://mail.qq.com/"},
            {"label": "阿里云邮件推送", "url": "https://dm.console.aliyun.com/"},
            {"label": "SendGrid", "url": "https://sendgrid.com/"},
            {"label": "Mailgun", "url": "https://www.mailgun.com/"},
        ],
        "note": "如果发件地址和 SMTP 账号不一致，很多服务商要求先在控制台验证发件域名。",
    },
}

SCHEMAS = {
    "qq": {"editable": True, "fields": QQ_FIELDS, "vendors": []},
    "wechat": {"editable": True, "fields": WECHAT_FIELDS, "vendors": []},
    "phone": {"editable": True, "fields": [], "vendors": PHONE_VENDORS},
    "email": {"editable": True, "fields": [], "vendors": EMAIL_VENDORS},
}


def _schema_fields(provider: str) -> list[dict]:
    schema = SCHEMAS[provider]
    if schema["fields"]:
        return schema["fields"]
    return [f for v in schema["vendors"] for f in v["fields"]]


def _all_keys(provider: str) -> set[str]:
    keys = {"enabled"}
    if provider in VENDOR_KEY:
        keys.add(VENDOR_KEY[provider])
    keys.update(f["key"] for f in _schema_fields(provider))
    return keys


def item(provider: str, callback_base: str = "") -> dict:
    raw = auth_providers.provider_settings(provider)
    schema = SCHEMAS[provider]
    vendor = str(raw.get(VENDOR_KEY.get(provider, "")) or DEFAULT_VENDOR.get(provider, ""))
    settings = {"enabled": bool(raw.get("enabled"))}
    if provider in VENDOR_KEY:
        settings[VENDOR_KEY[provider]] = vendor
    secrets: dict[str, bool] = {}
    for field in _schema_fields(provider):
        key = field["key"]
        if key in SECRET_KEYS.get(provider, ()):
            secrets[key] = bool(raw.get(key))
            continue
        value = raw.get(key, field.get("default", ""))
        if value in (None, ""):
            value = field.get("default", "")
        settings[key] = value
    callback_url = ""
    if provider in ("qq", "wechat") and callback_base:
        callback_url = callback_base.rstrip("/") + f"/api/auth/oauth/{provider}/callback"
    return {
        "key": provider,
        "label": auth_providers.LABELS[provider],
        "mode": auth_providers.MODES[provider],
        "enabled": provider == "username" or bool(raw.get("enabled")),
        "ready": auth_providers.configured(provider, raw),
        "editable": schema["editable"],
        "vendor": vendor,
        "vendor_key": VENDOR_KEY.get(provider, ""),
        "settings": settings,
        "secrets": secrets,
        "fields": schema["fields"],
        "vendors": schema["vendors"],
        "guide": GUIDES.get(provider, {}),
        "callback_url": callback_url,
    }


def admin_items(callback_base: str = "") -> list[dict]:
    out = [{
        "key": "username", "label": auth_providers.LABELS["username"], "mode": "password",
        "enabled": True, "ready": True, "editable": False, "vendor": "", "vendor_key": "",
        "settings": {}, "secrets": {}, "fields": [], "vendors": [], "guide": {},
        "callback_url": "",
    }]
    out.extend(item(p, callback_base) for p in ("phone", "email", "qq", "wechat"))
    return out


def _coerce(field: dict, value):
    if field["type"] == "checkbox":
        if isinstance(value, str):
            return value.lower() in ("1", "true", "on", "yes")
        return bool(value)
    if field["type"] == "number":
        try:
            return int(value)
        except Exception:
            return field.get("default", 0)
    return str(value or "").strip()


def save(provider: str, values: dict) -> dict:
    if provider not in SCHEMAS:
        raise ValueError("不支持这个登录方式")
    allowed = _all_keys(provider)
    fields = {f["key"]: f for f in _schema_fields(provider)}
    data = auth_providers._file_settings()
    entry = dict(data.get(provider) or {})
    for key, value in values.items():
        if key == "enabled":
            entry["enabled"] = (value.lower() in ("1", "true", "on", "yes")
                                if isinstance(value, str) else bool(value))
        elif key in VENDOR_KEY.values():
            vendor = str(value or "").strip()
            if vendor not in {v["key"] for v in SCHEMAS[provider]["vendors"]}:
                raise ValueError("未知的供应商")
            entry[key] = vendor
        elif key in allowed and key in fields:
            field = fields[key]
            if key in SECRET_KEYS.get(provider, ()):
                if value is None or str(value).strip() in ("", "••••••"):
                    continue
                entry[key] = encrypt(str(value).strip())
                continue
            entry[key] = _coerce(field, value)
        else:
            continue
    data[provider] = entry
    CONFIG_PATH = Path(auth_providers.CONFIG_PATH)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(CONFIG_PATH)
    return entry


def clear_secret(provider: str, key: str) -> None:
    if provider not in SCHEMAS or key not in SECRET_KEYS.get(provider, ()):
        raise ValueError("不是该登录方式的密钥字段")
    data = auth_providers._file_settings()
    entry = dict(data.get(provider) or {})
    entry[key] = ""
    data[provider] = entry
    CONFIG_PATH = Path(auth_providers.CONFIG_PATH)
    with _LOCK:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(CONFIG_PATH)
