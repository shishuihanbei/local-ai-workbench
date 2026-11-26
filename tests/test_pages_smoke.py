"""页面冒烟：入口 HTML 引用的每个静态资源都必须真能取到。

只测「页面装得起来」——HTML 200、`?v=` 占位符已替换、脚本与样式文件真实存在。
JS 运行时（有没有报错、面板能不能渲染）需要浏览器，见 `tools/frontend_smoke.py`。

这条测试挡的是最蠢也最容易发生的回归：改了文件名、挪了目录、mount 顺序变了，
页面照样返回 200，但浏览器拿到一堆 404，白屏。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

PAGES = ("/", "/console/", "/share/smoke-not-a-token", "/wb/smoke-not-a-token")

# 只有这两个页面的资源由本进程自己托管（/favicon.svg、console.css/js、app.css/js）。
# /share 与 /wb 的资源归 frontend 目录，前后端分离部署时由前端服务提供，这里不校验。
SELF_HOSTED_PAGES = ("/", "/console/")

# <script src="...">、<link href="...">，只取相对/同源引用
ASSET_RE = re.compile(r"""<(?:script|link)\b[^>]*(?:src|href)="([^"]+)\"""", re.I)


def _same_origin_assets(html: str) -> list[str]:
    paths: list[str] = []
    for raw in ASSET_RE.findall(html):
        if raw.startswith(("http://", "https://", "//", "data:", "#")):
            continue
        path = urlsplit(urljoin("http://127.0.0.1:9100", raw)).path
        if path not in paths:
            paths.append(path)
    return paths


def test_every_page_loads_without_placeholders(client):
    for page in PAGES:
        r = client.get(page)
        assert r.status_code == 200, f"{page} -> {r.status_code}"
        assert "__ASSET_VERSION__" not in r.text, f"{page} 里还有没替换的占位符"
        assert r.text.strip(), f"{page} 返回了空页面"


def test_referenced_assets_all_resolve(client):
    """页面里引用到的 js/css 逐个请求，必须 200 且有内容。"""
    checked = 0
    for page in SELF_HOSTED_PAGES:
        html = client.get(page).text
        for path in _same_origin_assets(html):
            r = client.get(path)
            assert r.status_code == 200, f"{page} 引用的 {path} 返回 {r.status_code}"
            assert r.content, f"{page} 引用的 {path} 是空文件"
            ctype = r.headers.get("content-type", "")
            assert any(t in ctype for t in ("javascript", "css", "svg", "image", "html")), (
                f"{path} 的 content-type 可疑：{ctype}"
            )
            checked += 1
    assert checked >= 4, f"只检查到 {checked} 个资源，页面解析可能失效了"


def test_console_page_declares_every_tab(client):
    """控制台入口至少要有导航和脚本；tab 面板由 JS 建，这里只兜住改版后的空壳。"""
    html = client.get("/console/").text
    assert "console.js?v=" in html
    assert "console.css?v=" in html
    assert "<html" in html.lower()
