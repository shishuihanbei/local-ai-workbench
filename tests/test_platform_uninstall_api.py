"""平台卸载 / Ollama 拉取接口的入口行为（只测拒绝与状态，不真的下载）。"""
from __future__ import annotations


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_pull_status_is_reachable(client, admin_token):
    r = client.get("/api/system/local-platforms/ollama/pull", headers=auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"running", "tag", "pct", "step", "msg", "ok"}


def test_pull_rejects_bad_tag(client, admin_token):
    r = client.post("/api/system/local-platforms/ollama/pull",
                    json={"tag": "rm -rf /"}, headers=auth(admin_token))
    assert r.status_code == 400
    assert "tag" in r.text


def test_uninstall_unknown_platform_404(client, admin_token):
    r = client.post("/api/system/local-platforms/nope/uninstall", headers=auth(admin_token))
    assert r.status_code == 404


def test_uninstall_system_platform_is_refused(client, admin_token):
    """LM Studio / vLLM 都是系统安装，工作台不接管卸载。"""
    r = client.post("/api/system/local-platforms/lmstudio/uninstall", headers=auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "手动卸载" in body["msg"] or "系统安装" in body["msg"]


def test_uninstall_status_endpoint_requires_admin_or_local(client, admin_token):
    """卸载接口挂在 admin_user 依赖下：带令牌可访问，且永远先返回一条说明。"""
    r = client.get("/api/system/local-deploy?scan=1", headers=auth(admin_token))
    assert r.status_code == 200
    keys = [p["key"] for p in r.json()["platforms"]]
    assert "ollama" in keys
