"""判断访问者在本机、内网还是外网，并给出对应的 API 地址。"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from ..config import load_config

_LAN_IP: str | None = None


def client_ip(request: Request) -> str:
    for header in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else ""


def lan_ip() -> str:
    """取本机局域网地址；取不到就退回 hostname 解析。"""
    global _LAN_IP
    if _LAN_IP:
        return _LAN_IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            _LAN_IP = ip
            return ip
    except Exception:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127."):
                _LAN_IP = ip
                return ip
    except Exception:
        pass
    return ""


def _is_private(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "")


def _host_parts(request: Request) -> tuple[str, str, str]:
    raw = (request.headers.get("x-forwarded-host") or request.headers.get("host")
           or request.url.netloc or "").split(",")[0].strip()
    try:
        parsed = urlsplit("//" + raw)
        host = parsed.hostname or ""
        netloc = (parsed.netloc or raw).rsplit("@", 1)[-1]
    except Exception:
        host = raw.split(":")[0]
        netloc = raw
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme
              or "http").split(",")[0].strip().lower()
    if scheme not in ("http", "https"):
        scheme = "http"
    return host.lower(), netloc, scheme


def origin(request: Request) -> str:
    """当前访问者实际使用的站点根地址（不包含路径）。"""
    _host, netloc, scheme = _host_parts(request)
    return f"{scheme}://{netloc}" if netloc else ""


def detect(request: Request) -> dict[str, Any]:
    cfg = load_config()
    port = int(cfg.get("port") or 9100)
    host, netloc, scheme = _host_parts(request)
    ip = client_ip(request)
    request_origin = f"{scheme}://{netloc}" if netloc else ""

    if _is_loopback(host):
        scope, label = "local", "本机"
        hint = "你当前从这台电脑本机访问，API 只在这台机器上可用。"
    elif _is_private(host):
        scope, label = "lan", "内网"
        hint = "你当前从同一局域网访问，局域网内的其他设备可以使用这个地址。"
    elif host.endswith(".trycloudflare.com") or request.headers.get("cf-connecting-ip"):
        scope, label = "external", "外网"
        scheme = "https"
        request_origin = f"{scheme}://{netloc}" if netloc else ""
        hint = "你当前通过公网穿透访问，任何能上网的设备都可以使用这个地址。"
    elif "." in host and not host.endswith(".local"):
        scope, label = "external", "外网"
        hint = "你当前通过公网域名访问，任何能上网的设备都可以使用这个地址。"
    else:
        scope, label = "lan", "内网"
        hint = "你当前通过局域网地址访问，同一内网的设备可以使用这个地址。"

    local_base = f"http://127.0.0.1:{port}/v1"
    ip_lan = lan_ip()
    if _is_private(host) and not _is_loopback(host):
        lan_base = f"{request_origin}/v1"
    else:
        lan_base = f"http://{ip_lan}:{port}/v1" if ip_lan else ""
    current_base = f"{request_origin}/v1" if request_origin else ""

    if scope == "local":
        recommended = local_base
    elif scope == "lan":
        recommended = lan_base or current_base
    else:
        recommended = current_base

    return {
        "scope": scope,
        "label": label,
        "hint": hint,
        "client_ip": ip,
        "host": host,
        "scheme": scheme,
        "port": port,
        "origin": request_origin,
        "recommended_base": recommended,
        "local_base": local_base,
        "lan_base": lan_base,
        "lan_ip": ip_lan,
        "current_base": current_base,
        "is_external": scope == "external",
    }
