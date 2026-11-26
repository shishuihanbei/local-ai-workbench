"""资源版本注入：HTML 里的 `?v=` 由后端按 ASSET_VERSION 填，不再手写。

目的：升级只改 `backend/version.py` 一处；页面和 JS/CSS 的缓存键永远同步，
不会出现「HTML 已更新、浏览器还在用旧 console.js」这种只在用户那头复现的问题。
"""
from __future__ import annotations

from backend.version import ASSET_VERSION


def test_console_serves_injected_version(client):
    r = client.get("/console/")
    assert r.status_code == 200
    html = r.text
    assert "__ASSET_VERSION__" not in html, "占位符没有被替换"
    assert "console.js?v=" in html and "console.css?v=" in html
    assert f"console.js?v={ASSET_VERSION}" in html
    assert f"console.css?v={ASSET_VERSION}" in html


def test_console_without_trailing_slash(client):
    r = client.get("/console", follow_redirects=False)
    assert r.status_code == 200
    assert f"console.js?v={ASSET_VERSION}" in r.text


def test_console_assets_still_reachable(client):
    """注入只改入口 HTML，静态资源仍由 mount 正常提供。"""
    for path in ("/console/console.js", "/console/console.css", "/console/favicon.svg"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.content


def test_meta_exposes_asset_version(client):
    body = client.get("/api/meta").json()
    assert body["asset_version"] == ASSET_VERSION
    assert body["version"]


def test_shared_pages_share_the_same_version(client):
    r = client.get("/share/not-a-real-token")
    assert r.status_code == 200
    assert "__ASSET_VERSION__" not in r.text
    assert f"share.js?v={ASSET_VERSION}" in r.text

    r = client.get("/wb/not-a-real-token")
    assert r.status_code == 200
    assert f"workbench-share.js?v={ASSET_VERSION}" in r.text
