"""本机判定回归：用本机局域网 IP 打开控制台也必须算「本机」。

背景：分享页 / 迁移包的「打开文件夹」曾经只认 127.0.0.1，用户在运行工作台的
同一台电脑上用 http://192.168.x.x:9100 打开页面时，后端看到的客户端 IP 是
192.168.x.x，于是被误判成远程访问，点了按钮直接报「只能在运行工作台的电脑上
打开这个文件夹」。现在改为「客户端 IP 属于本机所有网卡地址之一」。
"""
from __future__ import annotations

import pytest

from backend.services import netinfo


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("ip", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", "127.0.0.2"])
def test_loopback_is_local(ip: str):
    assert netinfo.is_local_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "10.255.255.1", "::ffff:8.8.8.8", "", "not-an-ip"])
def test_public_or_garbage_is_not_local(ip: str):
    assert netinfo.is_local_ip(ip) is False


def test_lan_ip_of_this_machine_is_local():
    """本机网卡地址（哪怕不是回环）必须判定为本机。"""
    lan = [ip for ip in netinfo.local_ips() if not ip.startswith("127.") and ip not in ("::1", "localhost")]
    if not lan:
        pytest.skip("这台机器没有局域网地址，无法验证")
    for ip in lan:
        assert netinfo.is_local_ip(ip) is True


def test_local_access_endpoint_reports_local(client, admin_token):
    r = client.get("/api/system/local-access", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["local"] is True  # TestClient 默认从 testclient 连进来，等同本机
    assert "client_ip" in body and "origin" in body


def test_remote_forwarded_ip_is_not_local(client, admin_token):
    """带 X-Forwarded-For 的外网地址必须判成远程，避免公网访问也能开本机文件夹。"""
    r = client.get(
        "/api/system/local-access",
        headers={**auth(admin_token), "x-forwarded-for": "8.8.8.8"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["local"] is False
