"""浏览器交互冒烟（Playwright）：真起一个服务、真开一个浏览器，点一遍关键路径。

默认不跑 —— 它要装浏览器内核、起进程，放进 pytest 全量回归太慢。
单独运行：`WORKBENCH_E2E=1 pytest -q tests/test_e2e_smoke.py`；
CI 的 e2e job 会装好浏览器并设这个环境变量。

覆盖 5 条路径：
  1. 用户端登录
  2. 发一条消息、收到流式回复
  3. 打开设置抽屉、切分区
  4. 控制台登录、改品牌副标题并保存
  5. 分享页只读渲染
每条都顺手收集 console error，任何一条红字都算失败。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

if os.getenv("WORKBENCH_E2E") != "1":
    pytest.skip("浏览器交互冒烟默认跳过；设 WORKBENCH_E2E=1 才跑", allow_module_level=True)

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent
ADMIN = "e2e-admin"
PASSWORD = "E2e-pass-2026"
# 拆成多段下发，模拟真实的 SSE 分块，顺便验证前端是逐段渲染而不是等整包
REPLY_CHUNKS = ["这是一段", "冒烟测试", "回复。"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _StubUpstream(BaseHTTPRequestHandler):
    """假的 OpenAI 兼容服务：/v1/models 让平台探测认出模型，/v1/chat/completions 按 SSE 吐固定回复。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802
        body = json.dumps({"object": "list", "data": [{"id": "e2e-model", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - http.server 的约定命名
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for text in REPLY_CHUNKS:
            payload = {"choices": [{"index": 0, "delta": {"content": text}}]}
            self.wfile.write(b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()
            time.sleep(0.03)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, *args):  # 静音
        pass


@pytest.fixture(scope="session")
def e2e_server():
    data_dir = Path(tempfile.mkdtemp(prefix="workbench-e2e-"))
    stub_port, app_port = _free_port(), _free_port()

    stub = ThreadingHTTPServer(("127.0.0.1", stub_port), _StubUpstream)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()

    # 配置走 data/config.json；桌面快捷方式关掉，免得往真桌面丢图标
    (data_dir / "config.json").write_text(json.dumps({
        "host": "127.0.0.1",
        "port": app_port,
        "serve_frontend": True,
        "upstream_base": f"http://127.0.0.1:{stub_port}/v1",
        "upstream_key": "sk-e2e",
        "upstream_port": stub_port,
        "model": "e2e-model",
        "local_enabled": True,
        "desktop_shortcuts": False,
        "kb_enabled": True,
        "library_enabled": True,
        "allow_register": False,
        "websearch_enabled": False,
        # 把假上游当成「自定义 OpenAI 兼容平台」，模型才会进前端下拉；
        # 不这样前端会拦一句「当前账号没有可用模型」，压根发不出消息
        "deploy_platforms": ["custom"],
        "platform_endpoints": {"custom": f"http://127.0.0.1:{stub_port}"},
    }, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ)
    env["WORKBENCH_DATA"] = str(data_dir)
    env["WORKBENCH_SECRET"] = "e2e-secret-key-do-not-use-in-production"
    # 模型目录也指到临时目录，避免读到本机真实模型，本地与 CI 行为才一致
    env["WORKBENCH_MODELS"] = str(data_dir / "models")
    env.pop("WORKBENCH_SERVE_FRONTEND", None)
    log_file = data_dir / "server.log"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=log_file.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)

    base = f"http://127.0.0.1:{app_port}"
    try:
        deadline = time.time() + 90
        while True:
            if proc.poll() is not None:
                raise RuntimeError("服务启动失败：\n" + log_file.read_text("utf-8")[-3000:])
            try:
                if httpx.get(base + "/api/health", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            if time.time() > deadline:
                raise RuntimeError("服务 90 秒内没起来：\n" + log_file.read_text("utf-8")[-3000:])
            time.sleep(0.5)

        r = httpx.post(base + "/api/auth/setup",
                       json={"username": ADMIN, "password": PASSWORD}, timeout=10)
        assert r.status_code == 200, f"初始化管理员失败：{r.status_code} {r.text}"
        token = r.json()["access_token"]
        yield {"base": base, "token": token, "api": {"Authorization": "Bearer " + token}}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        stub.shutdown()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        handle = None
        last_error: Exception | None = None
        for kwargs in ({"channel": "chromium"}, {}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                handle = p.chromium.launch(args=["--no-sandbox"], **kwargs)
                break
            except Exception as exc:  # 浏览器没装 / 起不来
                last_error = exc
        if handle is None:
            pytest.skip(f"没有可用的 Chromium 内核：{last_error}")
        yield handle
        handle.close()


def _new_page(browser):
    """新开一个干净上下文，返回 (page, errors)。console.error 与未捕获异常都记进 errors。"""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


def _login_user(page, base: str, tries: int = 3):
    """走登录界面登录。

    前端的 boot() 是异步的：它要 await 拉品牌与登录方式，之后才把登录表单露出来；
    偶发情况下表单露出来了但这一轮 fill 的内容被随后的渲染清掉，点提交就变成空表单。
    所以这里「填 → 点 → 等 appView」失败就重来一次，并把页面上的报错带出来。
    """
    last = ""
    for attempt in range(tries):
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_selector("#authUser", state="visible", timeout=20000)
        page.fill("#authUser", ADMIN)
        page.fill("#authPass", PASSWORD)
        page.click("#authSubmit")
        try:
            page.wait_for_selector("#appView", state="visible", timeout=15000)
            return
        except Exception:
            note = ""
            try:
                note = page.inner_text("#authError") if page.is_visible("#authError") else ""
            except Exception:
                pass
            last = f"第 {attempt + 1} 次登录没进主界面；表单报错={note!r}，url={page.url}"
    raise AssertionError(last)


def _api_login(base: str) -> tuple[str, str]:
    r = httpx.post(base + "/api/auth/login",
                   json={"username": ADMIN, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"接口登录失败：{r.status_code} {r.text}"
    return r.cookies.get("wb_session"), r.cookies.get("wb_csrf")


def _open_app(browser, server):
    """不走登录界面，直接带会话 cookie 进主界面。

    登录界面本身由 test_user_login_renders_app 覆盖；其余用例没必要反复点它，
    少一次 UI 时序依赖，CI 才不容易抖。
    """
    ctx, page, errors = _new_page(browser)
    sess, csrf = _api_login(server["base"])
    ctx.add_cookies([
        {"name": "wb_session", "value": sess, "url": server["base"] + "/"},
        {"name": "wb_csrf", "value": csrf or "", "url": server["base"] + "/"},
    ])
    page.goto(server["base"] + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#appView", state="visible", timeout=25000)
    return ctx, page, errors



def _wait_text(page, selector: str, want: str, timeout: float = 30):
    """等到 selector 的文字里出现 want。

    不用 page.wait_for_function 传字符串：页面带 CSP（script-src 'self'），
    字符串会被当成 eval 执行，直接报 EvalError。这里自己轮询 innerText。
    """
    deadline = time.time() + timeout
    got = ""
    while time.time() < deadline:
        try:
            got = page.inner_text(selector) or ""
        except Exception:
            got = ""
        if want in got:
            return got
        page.wait_for_timeout(200)
    raise AssertionError(f"{selector} 在 {timeout}s 内没等到 {want!r}，实际：{got[:200]!r}")



def test_user_login_renders_app(browser, e2e_server):
    ctx, page, errors = _new_page(browser)
    try:
        _login_user(page, e2e_server["base"])
        assert page.is_visible("#convList")
        assert ADMIN in page.inner_text("#userChip")
        assert errors == [], f"登录过程有 console 报错：{errors}"
    finally:
        ctx.close()


def test_send_message_streams_reply(browser, e2e_server):
    ctx, page, errors = _open_app(browser, e2e_server)
    try:
        # 模型下拉是登录后才拉的（要探测平台），等它真的选上模型再发；
        # 否则前端会先弹「当前账号没有可用模型」，请求根本没发出去
        page.wait_for_selector("#modelSelect option", state="attached", timeout=25000)
        deadline = time.time() + 25
        while time.time() < deadline and not page.input_value("#modelSelect"):
            page.wait_for_timeout(200)
        assert page.input_value("#modelSelect"), "模型下拉一直没选中任何模型"
        page.fill("#messageInput", "你好，做个自检")
        page.press("#messageInput", "Enter")
        text = _wait_text(page, "#messages", "".join(REPLY_CHUNKS), timeout=30)
        assert "你好，做个自检" in text, f"用户消息没上屏：{text[:200]}"
        assert errors == [], f"发消息过程有 console 报错：{errors}"
    finally:
        ctx.close()


def test_settings_drawer_opens_and_switches(browser, e2e_server):
    ctx, page, errors = _open_app(browser, e2e_server)
    try:
        page.click("#userChip")
        page.wait_for_selector("#settingsDrawer", state="visible", timeout=15000)
        assert "active" in (page.locator("#dpanel-account").get_attribute("class") or "")
        page.click("[data-dtab='chat']")
        deadline = time.time() + 15
        while time.time() < deadline:
            if "active" in (page.locator("#dpanel-chat").get_attribute("class") or ""):
                break
            page.wait_for_timeout(150)
        else:
            raise AssertionError("切到「对话」分区后 #dpanel-chat 没有变成 active")
        assert page.is_visible("#setTemp"), "对话分区内容没渲染出来"
        page.click("[data-dtab='account']")
        page.click("#settingsDrawer button[data-close-settings]")
        page.wait_for_selector("#settingsDrawer", state="hidden", timeout=15000)
        assert errors == [], f"设置抽屉有 console 报错：{errors}"
    finally:
        ctx.close()


def test_console_login_and_save_branding(browser, e2e_server):
    ctx, page, errors = _new_page(browser)
    base = e2e_server["base"]
    try:
        page.goto(base + "/console/", wait_until="domcontentloaded")
        page.wait_for_selector("#loginForm", state="visible", timeout=20000)
        page.fill("#u", ADMIN)
        page.fill("#p", PASSWORD)
        page.click("#loginBtn")
        page.wait_for_selector("#loginWrap", state="hidden", timeout=20000)
        page.click("[data-tab='org']")
        page.wait_for_selector("#brandTagline", state="visible", timeout=15000)
        deadline = time.time() + 15
        while time.time() < deadline and not page.input_value("#brandTagline"):
            page.wait_for_timeout(150)
        assert page.input_value("#brandTagline"), "外观页没把现有品牌副标题读出来"
        tagline = "E2E 冒烟副标题"
        page.fill("#brandTagline", tagline)
        page.click("#saveOrgBtn")
        _wait_text(page, "#orgSaveHint", "保存", timeout=15)

        org = httpx.get(base + "/api/admin/org", headers=e2e_server["api"], timeout=10).json()
        assert str(org.get("brand_tagline") or "") == tagline, f"品牌副标题没落库：{org}"
        assert errors == [], f"控制台有 console 报错：{errors}"
    finally:
        ctx.close()


def test_shared_conversation_page(browser, e2e_server):
    base, headers = e2e_server["base"], e2e_server["api"]
    conv = httpx.post(base + "/api/chat/conversations", headers=headers,
                      json={"title": "冒烟分享"}, timeout=10).json()
    cid = conv["id"]
    with httpx.Client(timeout=60) as client:
        with client.stream("POST", base + "/api/chat/stream", headers=headers,
                           json={"conversation_id": cid, "message": "分享页用这条"}) as r:
            assert r.status_code == 200, r.read()
            for _ in r.iter_lines():
                pass
    share = httpx.post(base + f"/api/conversations/{cid}/share", headers=headers,
                       json={"visibility": "public"}, timeout=10).json()
    token = share["token"]

    ctx, page, errors = _new_page(browser)
    try:
        page.goto(f"{base}/share/{token}", wait_until="domcontentloaded")
        body = _wait_text(page, "#messages", "".join(REPLY_CHUNKS), timeout=20)
        assert "冒烟分享" in page.inner_text("#title")
        assert errors == [], f"分享页有 console 报错：{errors}"
    finally:
        ctx.close()
