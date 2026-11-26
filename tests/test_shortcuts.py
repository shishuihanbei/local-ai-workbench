"""桌面快捷方式：三平台写入内容、删除、容器内不支持、首次自动创建。"""
from __future__ import annotations

import plistlib
from pathlib import Path


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _fake(tmp_path, monkeypatch, platform: str = "win32", docker: bool = False):
    from backend.services import shortcuts

    desktop = tmp_path / "Desktop"
    desktop.mkdir(exist_ok=True)
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: desktop)
    monkeypatch.setattr(shortcuts.sys, "platform", platform)
    monkeypatch.setattr(shortcuts, "_in_docker", lambda: docker)
    monkeypatch.setattr(shortcuts, "MARKER", tmp_path / ".shortcut_marker")
    monkeypatch.setattr(shortcuts, "BASE_DIR", tmp_path)
    monkeypatch.setattr(shortcuts, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        shortcuts, "load_config",
        lambda: {"org_short_name": "AI 工作台", "port": 9123, "frontend_url": "",
                 "desktop_shortcuts": True},
    )
    monkeypatch.delenv("WORKBENCH_PORT", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return shortcuts, desktop


def test_shortcuts_initial_status(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["supported"] is True
    assert len(st["items"]) == 2
    assert all(not x["exists"] for x in st["items"])
    assert st["urls"]["console"].endswith("/console/")
    assert st["urls"]["front"].startswith("http://127.0.0.1:9123")
    assert st["message"]


def test_shortcuts_create_and_remove_windows(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch)
    h = auth(admin_token)
    res = client.post("/api/system/shortcuts", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    front = desktop / "AI 工作台.url"
    console = desktop / "AI 工作台-后台.url"
    assert front.exists() and console.exists()
    text = front.read_text("utf-8")
    assert "[InternetShortcut]" in text and "URL=http://127.0.0.1:9123/" in text
    assert "URL=http://127.0.0.1:9123/console/" in console.read_text("utf-8")

    again = client.get("/api/system/shortcuts", headers=h).json()
    assert all(x["exists"] for x in again["items"])

    off = client.delete("/api/system/shortcuts", headers=h)
    assert off.status_code == 200
    assert off.json()["ok"] is True
    assert not front.exists() and not console.exists()


def test_shortcuts_linux_desktop_entry(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch, platform="linux2")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    entry = (desktop / "AI 工作台.desktop").read_text("utf-8")
    assert "[Desktop Entry]" in entry
    assert 'Exec=xdg-open "http://127.0.0.1:9123/"' in entry
    assert "Name=AI 工作台" in entry
    assert (desktop / "AI 工作台-后台.desktop").exists()
    # 同时进应用菜单
    assert (tmp_path / ".local" / "share" / "applications" / "AI 工作台.desktop").exists()


def test_shortcuts_macos_webloc(client, admin_token, tmp_path, monkeypatch):
    _, desktop = _fake(tmp_path, monkeypatch, platform="darwin")
    res = client.post("/api/system/shortcuts", headers=auth(admin_token))
    assert res.status_code == 200, res.text
    with open(desktop / "AI 工作台.webloc", "rb") as fh:
        data = plistlib.load(fh)
    assert data["URL"] == "http://127.0.0.1:9123/"


def test_shortcuts_unsupported_in_docker(client, admin_token, tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch, platform="linux2", docker=True)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["platform"] == "docker"
    assert st["supported"] is False
    assert client.post("/api/system/shortcuts", headers=auth(admin_token)).status_code == 400


def test_shortcuts_headless_linux_only_links(client, admin_token, tmp_path, monkeypatch):
    shortcuts, _ = _fake(tmp_path, monkeypatch, platform="linux2")
    monkeypatch.setattr(shortcuts, "_linux_has_desktop", lambda: False)
    st = client.get("/api/system/shortcuts", headers=auth(admin_token)).json()
    assert st["supported"] is False
    assert "服务器" in st["message"]
    assert st["urls"]["console"].startswith("http://127.0.0.1:9123")
    assert client.post("/api/system/shortcuts", headers=auth(admin_token)).status_code == 400


def test_shortcuts_ensure_once(tmp_path, monkeypatch):
    shortcuts, desktop = _fake(tmp_path, monkeypatch)
    monkeypatch.setenv("WORKBENCH_PORT", "9123")
    first = shortcuts.ensure_once()
    assert first and first["ok"] is True
    assert (desktop / "AI 工作台.url").exists()
    assert shortcuts.MARKER.exists()
    assert shortcuts.ensure_once() is None  # 已有标记，不重复创建
