"""短信 / 邮件验证码发送。

短信内置阿里云、腾讯云、云片和自定义 HTTP；邮件走标准 SMTP。
所有发送都在线程里执行，避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import parse_qsl, quote

import httpx


class DeliveryError(Exception):
    pass


PHONE_RE = re.compile(r"\+?\d{6,20}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def normalize_phone(raw: str, country_code: str = "+86") -> str:
    value = re.sub(r"[\s-]", "", str(raw or "").strip())
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+"):
        return value
    if len(value) == 11 and value.startswith("1"):
        return country_code + value
    return value


def _aliyun_sms(cfg: dict, phone: str, code: str) -> str:
    key = str(cfg.get("sms_key") or "").strip()
    secret = str(cfg.get("sms_secret") or "").strip()
    sign = str(cfg.get("sms_sign") or "").strip()
    template = str(cfg.get("sms_template") or "").strip()
    if not (key and secret and sign and template):
        raise DeliveryError("阿里云短信需要 AccessKey ID、AccessKey Secret、签名和模板 CODE")
    params = {
        "AccessKeyId": key,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": re.sub(r"^\+86", "", phone),
        "RegionId": str(cfg.get("sms_region") or "cn-hangzhou"),
        "SignName": sign,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": f"{int(time.time() * 1000)}-{time.perf_counter_ns()}",
        "SignatureVersion": "1.0",
        "TemplateCode": template,
        "TemplateParam": json.dumps({"code": code}, ensure_ascii=False),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    encoded = "&".join(f"{quote(k, safe='~')}={quote(str(v), safe='~')}"
                       for k, v in sorted(params.items()))
    string_to_sign = "POST&%2F&" + quote(encoded, safe="~")
    digest = hmac.new((secret + "&").encode(), string_to_sign.encode(), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(digest).decode()
    response = httpx.post("https://dysmsapi.aliyuncs.com/", data=params, timeout=20)
    if response.status_code >= 400:
        raise DeliveryError(f"阿里云短信 HTTP {response.status_code}")
    try:
        data = response.json()
    except Exception:
        raise DeliveryError("阿里云短信返回不是 JSON")
    if data.get("Code") != "OK":
        raise DeliveryError(f"阿里云短信：{data.get('Code') or '失败'} {data.get('Message') or ''}".strip())
    return "阿里云短信已发送"


def _tencent_hash(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _tencent_sms(cfg: dict, phone: str, code: str) -> str:
    secret_id = str(cfg.get("sms_key") or "").strip()
    secret_key = str(cfg.get("sms_secret") or "").strip()
    app_id = str(cfg.get("sms_app_id") or "").strip()
    sign = str(cfg.get("sms_sign") or "").strip()
    template = str(cfg.get("sms_template") or "").strip()
    region = str(cfg.get("sms_region") or "ap-guangzhou").strip()
    if not (secret_id and secret_key and app_id and sign and template):
        raise DeliveryError("腾讯云短信需要 SecretId、SecretKey、SdkAppId、签名和模板 ID")
    host = "sms.tencentcloudapi.com"
    service = "sms"
    action = "SendSms"
    version = "2021-03-11"
    payload = json.dumps({
        "PhoneNumberSet": [phone],
        "SmsSdkAppId": app_id,
        "SignName": sign,
        "TemplateId": template,
        "TemplateParamSet": [code],
    }, ensure_ascii=False, separators=(",", ":"))
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
    content_type = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{content_type}\nhost:{host}\n"
    signed_headers = "content-type;host"
    canonical_request = (f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n"
                         f"{hashlib.sha256(payload.encode()).hexdigest()}")
    scope = f"{date}/{service}/tc3_request"
    string_to_sign = (f"TC3-HMAC-SHA256\n{timestamp}\n{scope}\n"
                      f"{hashlib.sha256(canonical_request.encode()).hexdigest()}")
    k_date = _tencent_hash(("TC3" + secret_key).encode(), date)
    k_service = _tencent_hash(k_date, service)
    k_signing = _tencent_hash(k_service, "tc3_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}")
    headers = {
        "Authorization": auth,
        "Content-Type": content_type,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }
    response = httpx.post(f"https://{host}/", content=payload, headers=headers, timeout=20)
    if response.status_code >= 400:
        raise DeliveryError(f"腾讯云短信 HTTP {response.status_code}")
    try:
        data = response.json().get("Response") or {}
    except Exception:
        raise DeliveryError("腾讯云短信返回不是 JSON")
    if data.get("Error"):
        raise DeliveryError(f"腾讯云短信：{data['Error'].get('Code')} {data['Error'].get('Message')}")
    item = (data.get("SendStatusSet") or [{}])[0]
    if item.get("Code") != "Ok":
        raise DeliveryError(f"腾讯云短信：{item.get('Code') or '失败'} {item.get('Message') or ''}".strip())
    return "腾讯云短信已发送"


def _yunpian_sms(cfg: dict, phone: str, code: str) -> str:
    key = str(cfg.get("sms_key") or "").strip()
    if not key:
        raise DeliveryError("云片短信需要 APIKEY")
    template = str(cfg.get("sms_template") or "").strip() or "您的验证码是{code}，5分钟内有效。"
    text = template.replace("{code}", code)
    sign = str(cfg.get("sms_sign") or "").strip()
    if sign and not text.startswith("【"):
        text = f"【{sign}】{text}"
    response = httpx.post("https://sms.yunpian.com/v2/sms/single_send.json",
                          data={"apikey": key, "mobile": re.sub(r"^\+86", "", phone), "text": text},
                          timeout=20)
    try:
        data = response.json()
    except Exception:
        raise DeliveryError(f"云片短信 HTTP {response.status_code}")
    if response.status_code >= 400 or int(data.get("code") or -1) != 0:
        raise DeliveryError(f"云片短信：{data.get('code')} {data.get('msg') or data.get('detail') or ''}".strip())
    return "云片短信已发送"


def _render(value: str, phone: str, code: str, cfg: dict) -> str:
    return (value.replace("{phone}", phone).replace("{code}", code)
            .replace("{sign}", str(cfg.get("sms_sign") or ""))
            .replace("{template}", str(cfg.get("sms_template") or "")))


def _custom_sms(cfg: dict, phone: str, code: str) -> str:
    url = _render(str(cfg.get("sms_url") or "").strip(), phone, code, cfg)
    if not url:
        raise DeliveryError("自定义短信需要填写请求地址")
    if not url.startswith(("http://", "https://")):
        raise DeliveryError("短信请求地址必须以 http:// 或 https:// 开头")
    method = str(cfg.get("sms_method") or "POST").upper()
    try:
        headers = json.loads(cfg.get("sms_headers") or "{}")
    except Exception:
        raise DeliveryError("短信请求头不是合法 JSON")
    if not isinstance(headers, dict):
        raise DeliveryError("短信请求头必须是 JSON 对象")
    body = _render(str(cfg.get("sms_body") or ""), phone, code, cfg)
    kwargs = {"headers": {str(k): str(v) for k, v in headers.items()}, "timeout": 20}
    if method == "GET":
        try:
            params = json.loads(body) if body else {}
        except Exception:
            params = dict(parse_qsl(body, keep_blank_values=True))
        kwargs["params"] = params
    else:
        try:
            payload = json.loads(body) if body else {}
            kwargs["json"] = payload
        except Exception:
            kwargs["content"] = body
    response = httpx.request(method, url, **kwargs)
    text = response.text[:400]
    if response.status_code >= 400:
        raise DeliveryError(f"短信接口 HTTP {response.status_code}：{text[:160]}")
    mark = str(cfg.get("sms_success") or "").strip()
    if mark and mark not in response.text:
        raise DeliveryError(f"短信接口未返回预期成功标记：{text[:160]}")
    return "自定义短信接口已返回成功"


def send_sms_sync(cfg: dict, phone: str, code: str) -> str:
    vendor = str(cfg.get("sms_vendor") or ("custom" if cfg.get("sms_url") else "aliyun"))
    phone = normalize_phone(phone)
    if not PHONE_RE.fullmatch(phone):
        raise DeliveryError("手机号格式不正确")
    if vendor == "aliyun":
        return _aliyun_sms(cfg, phone, code)
    if vendor == "tencent":
        return _tencent_sms(cfg, phone, code)
    if vendor == "yunpian":
        return _yunpian_sms(cfg, phone, code)
    if vendor == "custom":
        return _custom_sms(cfg, phone, code)
    raise DeliveryError(f"不支持的短信供应商：{vendor}")


def _send_email_sync(cfg: dict, to: str, subject: str, text: str) -> str:
    host = str(cfg.get("smtp_host") or "").strip()
    user = str(cfg.get("smtp_user") or "").strip()
    password = str(cfg.get("smtp_password") or "")
    sender = str(cfg.get("smtp_from") or user).strip()
    if not host or not user or not sender:
        raise DeliveryError("邮件服务需要 SMTP 主机、账号和发件地址")
    if not EMAIL_RE.fullmatch(to):
        raise DeliveryError("收件邮箱格式不正确")
    try:
        port = int(cfg.get("smtp_port") or 465)
    except Exception:
        raise DeliveryError("SMTP 端口必须是数字")
    use_ssl = bool(cfg.get("smtp_ssl")) or port == 465
    starttls = bool(cfg.get("smtp_starttls")) and not use_ssl
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((str(cfg.get("smtp_name") or "AI 工作台"), sender))
    msg["To"] = to
    msg.set_content(text)
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            server.ehlo()
            if starttls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if user:
                server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise DeliveryError(f"SMTP 登录失败，请检查账号和授权码（{exc.smtp_code}）") from exc
    except Exception as exc:
        raise DeliveryError(f"邮件发送失败：{type(exc).__name__}: {str(exc)[:160]}") from exc
    return "测试邮件已发送"


async def send_sms(cfg: dict, phone: str, code: str) -> str:
    return await asyncio.to_thread(send_sms_sync, cfg, phone, code)


async def send_email(cfg: dict, to: str, subject: str, text: str) -> str:
    return await asyncio.to_thread(_send_email_sync, cfg, to, subject, text)
