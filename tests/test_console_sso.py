"""控制台免二次登录（同源 cookie 复用）与用户端底部账号行布局的静态约束。

这些断言只读源码，防止以后改回去：
- 用户端不再有「本地模式」提示卡，管理控制台入口与账号行并排；
- 控制台启动引导先认 cookie 会话，不再以 localStorage 令牌为唯一条件；
- 控制台请求在只有 cookie 时带上 CSRF 头。
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
CONSOLE = ROOT / "backend" / "console"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_user_sidebar_has_no_local_mode_card():
    html = _read(FRONTEND / "index.html")
    assert "localModeCard" not in html
    assert "本地模式" not in html
    assert "对话与文件不离开这台电脑" not in html


def test_console_entry_sits_in_user_row():
    html = _read(FRONTEND / "index.html")
    foot = html.split('class="sidebar-foot"', 1)[1].split("</aside>", 1)[0]
    assert 'class="user-row"' in foot
    assert 'id="userChip"' in foot
    assert 'id="consoleEntry"' in foot
    row = foot.split('class="user-row"', 1)[1]
    assert 'id="consoleEntry"' in row and 'id="userChip"' in row
    assert "console-chip" not in foot


def test_console_boot_accepts_cookie_session():
    boot = _read(CONSOLE / "boot.js")
    assert "/api/auth/me" in boot
    assert "cookieSession" in boot
    # 不再因为 localStorage 没令牌就直接弹登录
    assert "if (!token()) { showLogin(); return; }" not in boot
    assert "showLogin(true)" in boot  # 未初始化仍走初始化引导


def test_console_api_sends_csrf_with_cookie_session():
    core = _read(CONSOLE / "core.js")
    assert 'cookieValue("wb_csrf")' in core
    assert '"X-CSRF-Token"' in core
    assert "function signedIn()" in core


def test_console_tab_switch_uses_signed_in():
    tabs = _read(CONSOLE / "tabs.js")
    assert "if (!token()) { showLogin(); return; }" not in tabs
    assert "if (!token()) { showLogin(); return { ok: false" not in tabs
    assert "signedIn()" in tabs
