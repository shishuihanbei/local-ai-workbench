"""桌面图标：一个入口、双击进后台、右键前后台、三平台写入、地址可选。"""
from __future__ import annotations

import plistlib
from pathlib import Path

import pytest


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _fake(tmp_path, monkeypatch, platform: str = "win32", docker: bool = False, drop_mode: bool = False, **cfg_extra):
    from backend.services import shortcuts

    desktop = tmp_path / "Desktop"
    desktop.mkdir(exist_ok=True)
    (tmp_path / "open.ps1").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "open.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcuts.sys, "platform", platform)
    monkeypatch.setattr(shortcuts, "_in_docker", lambda: docker)
    monkeypatch.setattr(shortcuts, "_linux_has_desktop", lambda: True)
    monkeypatch.setattr(shortcuts, "MARKER", tmp_path / ".shortcut_marker")
    monkeypatch.setattr(shortcuts, "BASE_DIR", tmp_path)
    monkeypatch.setattr(shortcuts, "DATA_DIR", tmp_path / "data")
    cfg = {"org_short_name": "AI 工作台", "port": 9123, "frontend_url": "",
           "desktop_shortcuts": True, "brand_primary": "#4f6ef7",
           "shortcut_mode": "local", "shortcut_lan_ip": "", "shortcut_custom_url": ""}
    if drop_mode:
        cfg.pop("shortcut_mode")
        cfg.pop("shortcut_lan_ip")
    cfg.update(cfg_extra)
    monkeypatch.setattr(shortcuts, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(shortcuts, "_lan_candidates",
                        lambda: [{"ip": "192.168.5.38", "iface": "以太网"}, {"ip": "10.0.0.7", "iface": "Wi-Fi"}])
    monkeypatch.delenv("WORKBENCH_PORT", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return shortcuts, desktop


def _stub_windows_app():
    def write(path, url):
        path.write_bytes(b"wbapp")
        return True
    return write


def test_one_icon_initial_status(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["supported"] is True
    assert len(st["items"]) == 1 and st["items"][0]["key"] == "app"
    assert st["items"][0]["exists"] is False
    assert st["urls"]["console"].endswith("/console/")
    assert st["items"][0]["url"].startswith("http://127.0.0.1:9123/console")
    assert [v["label"] for v in st["verbs"]] == ["打开前台", "打开后台"]


def test_windows_creates_single_app_icon(client, admin_token, tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setattr(shortcuts, "_write_windows_app", _stub_windows_app())
    monkeypatch.setattr(shortcuts, "_remove_windows_app", lambda: None)
    # 旧版本留下的图标会被清理
    (desktop / "AI 工作台.lnk").write_bytes(b"old")
    (desktop / "AI 工作台.url").write_text("[InternetShortcut]\nURL=x\n", encoding="utf-8")
    (desktop / "AI 工作台-后台.url").write_text("[InternetShortcut]\nURL=x\n", encoding="utf-8")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert len(res.json()["items"]) == 1
    assert (desktop / "AI 工作台.wbapp").exists()
    assert not (desktop / "AI 工作台.lnk").exists()
    assert not (desktop / "AI 工作台-后台.url").exists()


def test_windows_fallback_to_url(client, admin_token, tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setattr(shortcuts, "_write_windows_app", lambda path, url: False)
    monkeypatch.setattr(shortcuts, "_remove_windows_app", lambda: None)
    res = client.post("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert res["ok"] is True
    assert (desktop / "AI 工作台.url").exists()


def test_linux_desktop_entry_has_actions(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch, platform="linux2")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    entry = (desktop / "AI 工作台.desktop").read_text("utf-8")
    assert "[Desktop Entry]" in entry
    assert 'Exec="' in entry and "open.sh" in entry and "console" in entry
    assert "Actions=Front;Console;" in entry
    assert "Name=打开前台" in entry and "Name=打开后台" in entry
    assert (tmp_path / ".local" / "share" / "applications" / "AI 工作台.desktop").exists()


def test_macos_webloc_opens_console(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch, platform="darwin")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    with open(desktop / "AI 工作台.webloc", "rb") as fh:
        data = plistlib.load(fh)
    assert data["URL"] == "http://127.0.0.1:9123/console/"


def test_default_mode_is_lan(client, admin_token, tmp_path, monkeypatch):
    """全新安装默认走局域网；没指定网卡时自动探测本机 LAN IP。"""
    from backend.config import DEFAULTS

    assert DEFAULTS["shortcut_mode"] == "lan"
    shortcuts, _ = _fake(tmp_path, monkeypatch, drop_mode=True,
                         shortcut_mode="lan", shortcut_lan_ip="")
    monkeypatch.setattr(shortcuts, "_lan_ip", lambda: "192.168.5.38")
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["mode"] == "lan"
    assert st["urls"]["console"] == "http://192.168.5.38:9123/console/"


def test_lan_mode_uses_chosen_ip(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch, shortcut_mode="lan", shortcut_lan_ip="192.168.5.38")
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["urls"]["console"] == "http://192.168.5.38:9123/console/"
    assert st["lan_ip"] == "192.168.5.38"
    assert {x["ip"] for x in st["lan_ips"]} == {"192.168.5.38", "10.0.0.7"}


def test_custom_mode_uses_https_base(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch, shortcut_mode="custom",
          shortcut_custom_url="https://ai.example.com/")
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["urls"]["front"] == "https://ai.example.com/"
    assert st["urls"]["console"] == "https://ai.example.com/console/"


def test_save_settings_validates_and_persists(client, admin_token, tmp_path, monkeypatch):
    from backend import config as cfgmod

    shortcuts, _ = _fake(tmp_path, monkeypatch)
    saved: dict = {}
    monkeypatch.setattr(cfgmod, "save_config", lambda cfg: saved.update(cfg))

    res = client.put("/api/system/shortcuts/settings", headers=auth(admin_token),
                     json={"mode": "lan", "lan_ip": "192.168.5.38"})
    assert res.status_code == 200, res.text
    assert saved["shortcut_mode"] == "lan" and saved["shortcut_lan_ip"] == "192.168.5.38"

    bad = client.put("/api/system/shortcuts/settings", headers=auth(admin_token),
                     json={"mode": "custom", "custom_url": "ai.example.com"})
    assert bad.status_code == 400
    bad_ip = client.put("/api/system/shortcuts/settings", headers=auth(admin_token),
                        json={"mode": "lan", "lan_ip": "not-an-ip"})
    assert bad_ip.status_code == 400


def test_remove_icon(client, admin_token, tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setattr(shortcuts, "_write_windows_app", _stub_windows_app())
    monkeypatch.setattr(shortcuts, "_remove_windows_app", lambda: None)
    client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert (desktop / "AI 工作台.wbapp").exists()
    off = client.delete("/api/system/shortcuts", headers=auth(admin_token))
    assert off.status_code == 200 and off.json()["ok"] is True
    assert not (desktop / "AI 工作台.wbapp").exists()


def test_unsupported_in_docker(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch, platform="linux2", docker=True)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["platform"] == "docker" and st["supported"] is False
    assert client.post("/api/system/shortcuts", headers=auth(admin_token)).status_code == 400


def test_headless_linux_only_links(client, admin_token, tmp_path, monkeypatch):
    shortcuts, _ = _fake(tmp_path, monkeypatch, platform="linux2")
    monkeypatch.setattr(shortcuts, "_linux_has_desktop", lambda: False)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["supported"] is False
    assert "服务器" in st["message"]
    assert client.post("/api/system/shortcuts", headers=auth(admin_token)).status_code == 400


def test_ensure_once(tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setattr(shortcuts, "_write_windows_app", _stub_windows_app())
    monkeypatch.setattr(shortcuts, "_remove_windows_app", lambda: None)
    first = shortcuts.ensure_once()
    assert first and first["ok"] is True
    assert (desktop / "AI 工作台.wbapp").exists()
    assert shortcuts.MARKER.exists()
    assert shortcuts.ensure_once() is None

    # 数据目录被 WORKBENCH_DATA 指走时不碰桌面
    monkeypatch.setattr(shortcuts, "DATA_DIR", tmp_path / "other-data")
    monkeypatch.setattr(shortcuts, "MARKER", tmp_path / "other-data" / ".marker")
    assert shortcuts.ensure_once() is None
