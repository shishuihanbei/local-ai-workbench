"""桌面图标：一个应用图标、三平台写入、删除、容器/服务器降级、首次自动创建。"""
from __future__ import annotations

import plistlib
from pathlib import Path


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _fake(tmp_path, monkeypatch, platform: str = "win32", docker: bool = False):
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
    monkeypatch.setattr(
        shortcuts, "load_config",
        lambda: {"org_short_name": "AI 工作台", "port": 9123, "frontend_url": "",
                 "desktop_shortcuts": True, "brand_primary": "#4f6ef7"},
    )
    monkeypatch.delenv("WORKBENCH_PORT", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return shortcuts, desktop


def test_one_icon_initial_status(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["supported"] is True
    assert len(st["items"]) == 1 and st["items"][0]["key"] == "app"
    assert st["items"][0]["exists"] is False
    assert st["urls"]["console"].endswith("/console/")
    assert st["items"][0]["url"] == "http://127.0.0.1:9123/"


def test_windows_creates_single_icon(client, admin_token, tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    # 不真跑 PowerShell：直接看有 open.ps1 时会走 .lnk 分支
    monkeypatch.setattr(shortcuts, "_write_windows_lnk",
                        lambda path, url, root: (path.write_bytes(b"lnk"), True)[1])
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert len(res.json()["items"]) == 1
    assert (desktop / "AI 工作台.lnk").exists()
    # 旧版本留下的「后台」图标会被清理
    (desktop / "AI 工作台-后台.url").write_text("[InternetShortcut]\nURL=x\n", encoding="utf-8")
    client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert not (desktop / "AI 工作台-后台.url").exists()


def test_windows_fallback_to_url(client, admin_token, tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setattr(shortcuts, "_write_windows_lnk", lambda path, url, root: False)
    res = client.post("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert res["ok"] is True
    assert (desktop / "AI 工作台.url").exists()


def test_linux_single_desktop_entry(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch, platform="linux2")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    entry = (desktop / "AI 工作台.desktop").read_text("utf-8")
    assert "[Desktop Entry]" in entry
    assert 'Exec="' in entry and "open.sh" in entry
    assert "Name=AI 工作台" in entry
    assert (tmp_path / ".local" / "share" / "applications" / "AI 工作台.desktop").exists()


def test_macos_single_webloc(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch, platform="darwin")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    with open(desktop / "AI 工作台.webloc", "rb") as fh:
        data = plistlib.load(fh)
    assert data["URL"] == "http://127.0.0.1:9123/"


def test_remove_icon(client, admin_token, tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setattr(shortcuts, "_write_windows_lnk",
                        lambda path, url, root: (path.write_bytes(b"lnk"), True)[1])
    client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert (desktop / "AI 工作台.lnk").exists()
    off = client.delete("/api/system/shortcuts", headers=auth(admin_token))
    assert off.status_code == 200 and off.json()["ok"] is True
    assert not (desktop / "AI 工作台.lnk").exists()


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
    monkeypatch.setattr(shortcuts, "_write_windows_lnk",
                        lambda path, url, root: (path.write_bytes(b"lnk"), True)[1])
    monkeypatch.setenv("WORKBENCH_PORT", "9123")
    first = shortcuts.ensure_once()
    assert first and first["ok"] is True
    assert (desktop / "AI 工作台.lnk").exists()
    assert shortcuts.MARKER.exists()
    assert shortcuts.ensure_once() is None

    # 数据目录被 WORKBENCH_DATA 指走时不碰桌面
    monkeypatch.setattr(shortcuts, "DATA_DIR", tmp_path / "other-data")
    monkeypatch.setattr(shortcuts, "MARKER", tmp_path / "other-data" / ".marker")
    assert shortcuts.ensure_once() is None
