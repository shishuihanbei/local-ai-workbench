"""部署页只描述本机实际装了的引擎：没装 llama.cpp 不占位，开关与服务按已装引擎写。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_llama_panel_can_be_hidden():
    html = _read("backend/console/index.html")
    assert 'id="installPanel"' in html
    assert "llama.cpp 状态" in html
    assert "<h2>本地部署状态</h2>" not in html


def test_install_panel_hidden_when_llama_absent():
    js = _read("backend/console/models.js")
    assert 'const panel = $("installPanel");' in js
    assert "panel.hidden = !llama.installed && !st.install.running" in js


def test_switch_and_service_talk_about_real_engines():
    js = _read("backend/console/models.js")
    assert "function engineLines(platforms, onlyRunning)" in js
    # 开关状态机里不该再出现“缺少 llama.cpp”这种把 llama.cpp 当默认前提的文案
    assert "缺少 llama.cpp" not in js
    assert "本机还没有部署任何本地引擎" in js
    assert "renderService(hw, models, (deploy || {}).platforms)" in js
    assert "本机还没有部署任何本地引擎</p>" in js


def test_deploy_page_shows_one_storage_root():
    html = _read("backend/console/index.html")
    assert 'id="engineHomePanel"' in html
    assert "下载与安装目录" in html
    assert "不写系统目录" in html
    js = _read("backend/console/models.js")
    assert "function renderEngineHome(" in js
    assert "/api/system/engine-home" in js
    assert 'id="engineHomeRows"' in html


def test_deploy_page_has_whole_machine_uninstall_panel():
    html = _read("backend/console/index.html")
    assert 'id="uninstallPanel"' in html
    assert "uninstall.bat" in html
    assert "-KeepModels" in html and "-KeepData" in html and "-DryRun" in html
    js = _read("backend/console/session.js")
    assert "copyUninstallBtn" in js


def test_platform_card_explains_how_to_use_after_deploy():
    js = _read("backend/console/models.js")
    assert "platform-usage" in js
    assert "接入与使用" in js
    assert "p.usage" in js and "u.curl" in js and "u.api_base" in js
    assert "已接入用户端" in js
    css = _read("backend/console/console.css")
    assert ".platform-usage" in css and ".usage-code" in css


def test_deploying_card_offers_cancel():
    js = _read("backend/console/models.js")
    assert 'data-pcancel=' in js
    assert "取消部署" in js
    assert "cancelled" in js
    sess = _read("backend/console/session.js")
    assert "/cancel" in sess
    assert "取消中…" in sess
