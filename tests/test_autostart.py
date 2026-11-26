"""开机自启：接口状态、开启、关闭。全部在临时目录模拟，不写真实系统启动项。"""
from __future__ import annotations


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _fake_env(tmp_path, monkeypatch, platform: str = "win32", docker: bool = False):
    """把 autostart 的路径、项目目录和平台都指到临时目录。"""
    from backend.services import autostart

    root = tmp_path / "workbench"
    root.mkdir()
    (root / "start.ps1").write_text("# stub\n", encoding="utf-8")
    (root / "run.py").write_text("# stub\n", encoding="utf-8")
    (root / "data").mkdir()
    monkeypatch.setattr(autostart, "BASE_DIR", root)
    monkeypatch.setattr(autostart, "DATA_DIR", root / "data")
    monkeypatch.setattr(autostart, "_win_startup_dir", lambda: tmp_path / "Startup")
    monkeypatch.setattr(autostart.sys, "platform", platform)
    monkeypatch.setattr(autostart, "_in_docker", lambda: docker)
    return autostart, root


def test_autostart_status_initial(client, admin_token, tmp_path, monkeypatch):
    _fake_env(tmp_path, monkeypatch)
    r = client.get("/api/system/autostart", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["supported"] is True
    assert st["enabled"] is False
    assert isinstance(st["port"], int)
    assert st["message"]


def test_autostart_enable_then_disable(client, admin_token, tmp_path, monkeypatch):
    auto, root = _fake_env(tmp_path, monkeypatch)
    h = auth(admin_token)

    on = client.post("/api/system/autostart", headers=h)
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["ok"] is True and body["enabled"] is True
    target = tmp_path / "Startup" / auto.WIN_STARTUP_FILE
    assert target.exists()
    text = target.read_text("utf-8")
    assert "start.ps1" in text
    assert "-NoBrowser" in text
    assert f"-Port {auto._port()}" in text
    assert "WORKBENCH_SERVE_FRONTEND=1" in text
    # 隐藏窗口：不再弹出控制台
    assert "WindowStyle Hidden" in text

    again = client.get("/api/system/autostart", headers=h)
    assert again.json()["enabled"] is True

    off = client.delete("/api/system/autostart", headers=h)
    assert off.status_code == 200, off.text
    assert off.json()["ok"] is True and off.json()["enabled"] is False
    assert not target.exists()


def test_autostart_stale_path_detected(client, admin_token, tmp_path, monkeypatch):
    auto, _ = _fake_env(tmp_path, monkeypatch)
    h = auth(admin_token)
    startup = tmp_path / "Startup"
    startup.mkdir(parents=True, exist_ok=True)
    (startup / auto.WIN_STARTUP_FILE).write_text("@echo off\r\n", encoding="utf-8")
    st = client.get("/api/system/autostart", headers=h).json()
    assert st["enabled"] is True
    assert st["stale"] is True


def test_autostart_unsupported_in_docker(client, admin_token, tmp_path, monkeypatch):
    _fake_env(tmp_path, monkeypatch, platform="linux", docker=True)
    st = client.get("/api/system/autostart", headers=auth(admin_token)).json()
    assert st["platform"] == "docker"
    assert st["supported"] is False
    on = client.post("/api/system/autostart", headers=auth(admin_token))
    assert on.status_code == 400
