"""本地部署开关要把装好的平台都算进来，不能只认 Ollama。"""
from __future__ import annotations

import time


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


_ITEMS = [
    {"key": "llama.cpp", "name": "llama.cpp", "kind": "managed", "selected": False,
     "installed": False, "healthy": False, "models": [], "base_url": ""},
    {"key": "ollama", "name": "Ollama", "kind": "external", "selected": False,
     "installed": True, "healthy": True, "models": ["qwen2.5:7b"], "base_url": "http://127.0.0.1:11434"},
    {"key": "lmstudio", "name": "LM Studio", "kind": "external", "selected": False,
     "installed": True, "healthy": False, "models": [], "base_url": "http://127.0.0.1:1234"},
    {"key": "vllm", "name": "vLLM", "kind": "external", "selected": False,
     "installed": False, "healthy": False, "models": [], "base_url": "http://127.0.0.1:8000"},
    {"key": "custom", "name": "自定义", "kind": "external", "selected": False,
     "installed": False, "healthy": False, "models": [], "base_url": "http://127.0.0.1:8001"},
]


def _patch(monkeypatch, cfg: dict):
    from backend.routers import system
    from backend.services import platform_deploy

    monkeypatch.setattr(system, "load_config", lambda: cfg)
    monkeypatch.setattr(system, "save_config", lambda c: cfg.update(c))

    async def items(_cfg, selected, _srv, scan=False):
        return [{**row, "selected": row["key"] in selected} for row in _ITEMS]

    monkeypatch.setattr(system, "_platform_items", items)

    async def srv_status():
        return {"running": False, "healthy": False, "models": []}

    monkeypatch.setattr(system.llama.server, "status", srv_status)
    return system, platform_deploy


def test_installed_platforms_auto_join_the_switch(client, admin_token, monkeypatch):
    cfg = {"deploy_platforms": ["llama.cpp"], "local_enabled": True}
    _patch(monkeypatch, cfg)

    r = client.get("/api/system/local-deploy", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert {"ollama", "lmstudio"}.issubset(set(data["selected"]))
    assert "vllm" not in data["selected"] and "custom" not in data["selected"]
    assert cfg["deploy_platforms"] == data["selected"]
    assert set(cfg["platform_auto_added"]) == {"ollama", "lmstudio"}
    ollama = [p for p in data["platforms"] if p["key"] == "ollama"][0]
    assert ollama["selected"] is True


def test_removing_a_platform_is_respected(client, admin_token, monkeypatch):
    cfg = {"deploy_platforms": ["llama.cpp"], "local_enabled": True}
    _patch(monkeypatch, cfg)
    client.get("/api/system/local-deploy", headers=auth(admin_token))
    cfg["deploy_platforms"] = ["llama.cpp", "ollama"]
    r = client.get("/api/system/local-deploy", headers=auth(admin_token))
    assert r.json()["selected"] == ["llama.cpp", "ollama"], "手动取消勾选后不该被自动塞回去"


def test_turning_switch_on_starts_installed_external_platforms(client, admin_token, monkeypatch):
    cfg = {"deploy_platforms": ["llama.cpp", "ollama", "lmstudio"], "local_enabled": False}
    _system, platform_deploy = _patch(monkeypatch, cfg)
    started: list[str] = []

    async def fake_deploy(key, force=False, endpoint=""):
        started.append(key)
        return {"ok": True, "msg": "启动成功"}

    async def fake_start(key, endpoint=""):
        started.append(key)
        return {"ok": True, "msg": "启动成功"}

    monkeypatch.setattr(platform_deploy, "deploy", fake_deploy)
    monkeypatch.setattr(platform_deploy, "start", fake_start)
    monkeypatch.setattr(platform_deploy, "is_running", lambda key: False)

    r = client.post("/api/system/local-deploy",
                    json={"enabled": True, "platforms": ["llama.cpp", "ollama", "lmstudio"]},
                    headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert "正在启动" in r.json()["msg"] and "LM Studio" in r.json()["msg"]
    time.sleep(0.4)
    assert started == ["lmstudio"], "在跑的 Ollama 不用重启，只拉起装了没跑的 LM Studio"
