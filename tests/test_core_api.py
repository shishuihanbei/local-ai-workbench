"""核心接口回归测试：健康、初始化登录、模型清单、备份恢复。"""
from __future__ import annotations

import io
import json
import zipfile


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "workbench-api"


def test_xiaomi_integration_is_removed(client, admin_token):
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert "xiaogpt" not in r.json()["features"]
    r = client.get("/api/xiaogpt/status", headers=auth(admin_token))
    assert r.status_code == 404


def test_setup_admin_and_login(client, admin_token):
    assert admin_token
    r = client.post("/api/auth/login", json={
        "username": "admin", "password": "Pytest-pass-2026",
    })
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"
    assert r.json()["access_token"]


def test_models_need_login(client):
    client.cookies.clear()
    r = client.get("/api/models")
    assert r.status_code == 401


def test_models_catalog_has_categories(client, admin_token):
    r = client.get("/api/models", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["items"]) >= 52
    categories = {m["category"] for m in data["items"]}
    assert {"text", "code", "image", "video", "audio", "embedding", "rerank"}.issubset(categories)
    assert any(m["installable"] for m in data["items"])
    assert any(not m["installable"] for m in data["items"])
    vision = [m for m in data["items"] if m["key"] == "qwen25-vl-7b"][0]
    assert vision["engine_repo"] == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert vision["engine_recommend"]
    assert "engines" in data


def test_independent_model_download_needs_engine(client, admin_token, monkeypatch):
    from backend.routers import models as models_router
    monkeypatch.setattr(models_router.engines, "ready_for", lambda engine, state=None: False)
    r = client.post("/api/models/qwen25-vl-7b/download", headers=auth(admin_token))
    assert r.status_code == 400
    assert "没安装" in r.json()["detail"]


def test_independent_model_download_starts_when_engine_ready(client, admin_token, monkeypatch):
    from backend.routers import models as models_router
    monkeypatch.setattr(models_router.engines, "ready_for", lambda engine, state=None: True)
    monkeypatch.setattr(models_router.hf_models, "start",
                        lambda key, repo: {"ok": True, "msg": "已开始下载", "state": {"key": key}})
    r = client.post("/api/models/qwen25-vl-7b/download", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["msg"] == "已开始下载"


def test_backup_requires_login(client):
    client.cookies.clear()
    r = client.get("/api/system/backup")
    assert r.status_code == 401


def test_backup_contains_secret_and_manifest(client, admin_token):
    r = client.get("/api/system/backup", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert {"workbench.db", "secret.key", "config.json", "manifest.json"}.issubset(names)
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["format"] == "workbench-backup"
        assert manifest["format_version"] == 1
        assert "workbench.db" in manifest["files"]
        assert len(manifest["files"]["workbench.db"]["sha256"]) == 64
        assert "xiaogpt_dir" not in json.loads(z.read("config.json"))


def test_restore_accepts_own_backup(client, admin_token):
    r = client.get("/api/system/backup", headers=auth(admin_token))
    assert r.status_code == 200
    files = {"file": ("backup.zip", r.content, "application/zip")}
    r2 = client.post("/api/system/restore", headers=auth(admin_token), files=files)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    assert body["restart_required"] is True
    # 恢复的是刚导出的同一份数据，服务应继续正常响应
    assert client.get("/api/health").status_code == 200


def test_api_docs_use_local_assets(client):
    """接口文档必须自带 Swagger UI 资源，断网也能打开，不能依赖 CDN。"""
    r = client.get("/api/docs")
    assert r.status_code == 200
    body = r.text
    assert "/api/docs-assets/swagger-ui-bundle.js" in body
    assert "/api/docs-assets/swagger-ui.css" in body
    assert "cdn.jsdelivr.net" not in body
    assert "script-src 'self' 'unsafe-inline'" in r.headers["content-security-policy"]
    assert "no-store" in r.headers["cache-control"]

    js = client.get("/api/docs-assets/swagger-ui-bundle.js")
    assert js.status_code == 200
    assert len(js.content) > 500_000
    css = client.get("/api/docs-assets/swagger-ui.css")
    assert css.status_code == 200
    assert len(css.content) > 50_000


def test_storage_paths_default_to_program_root(client, admin_token, tmp_path):
    from backend import config as cfgmod

    cfg = cfgmod.load_config()
    keys = ("models_dir", "platforms_dir", "llama_dir", "llama_bin")
    old = {k: cfg.get(k) for k in keys}
    try:
        r = client.get("/api/system/storage", headers=auth(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["defaults"]["models_dir"] == str(cfgmod.BASE_DIR / "models")
        assert body["defaults"]["platforms_dir"] == str(cfgmod.BASE_DIR / "platforms")
        assert not body["defaults"]["models_dir"].startswith("D:\\AI\\models"), body

        models = tmp_path / "models"
        platforms = tmp_path / "platforms"
        r = client.put("/api/system/storage", headers=auth(admin_token),
                       json={"models_dir": str(models), "platforms_dir": str(platforms)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["models_dir"] == str(models) and models.is_dir()
        assert body["platforms_dir"] == str(platforms) and platforms.is_dir()
        assert body["llama_dir"] == str(platforms / "llama.cpp")

        r = client.put("/api/system/storage", headers=auth(admin_token),
                       json={"models_dir": "relative/models"})
        assert r.status_code == 400
    finally:
        cfg = cfgmod.load_config()
        for key, value in old.items():
            if value is not None:
                cfg[key] = value
        cfgmod.save_config(cfg)


def test_frontend_settings_follow_access_host(client, admin_token):
    from backend import config as cfgmod

    cfg = cfgmod.load_config()
    old = cfg.get("serve_frontend")
    old_port = cfg.get("port")
    cfg["serve_frontend"] = True
    cfg["port"] = 9100
    cfg["shortcut_mode"] = "lan"
    cfg["shortcut_lan_ip"] = "192.168.5.38"
    cfgmod.save_config(cfg)
    try:
        r = client.get("/api/system/settings", headers={
            **auth(admin_token),
            "Host": "192.168.5.38:9100",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["frontend_url"] == "http://192.168.5.38:9100/"
        assert body["frontend_url_auto"] is True

        r = client.get("/api/system/settings", headers={
            **auth(admin_token),
            "Host": "127.0.0.1:9100",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # 本机打开控制台时，前端按钮默认走局域网（跟随桌面图标地址偏好）
        assert body["frontend_url"] == "http://192.168.5.38:9100/"
        assert body["request_origin"] == "http://127.0.0.1:9100"

        r = client.get("/api/system/settings", headers={
            **auth(admin_token),
            "Host": "ai.example.com",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "ai.example.com",
        })
        assert r.status_code == 200, r.text
        assert r.json()["frontend_url"] == "https://ai.example.com/"
    finally:
        cfg = cfgmod.load_config()
        cfg["serve_frontend"] = bool(old)
        if old_port is not None:
            cfg["port"] = old_port
        cfgmod.save_config(cfg)


def test_model_select_requires_downloaded_file(client, admin_token, tmp_path):
    from backend import config as cfgmod

    cfg = cfgmod.load_config()
    old = cfg.get("models_dir")
    cfg["models_dir"] = str(tmp_path / "models")
    tmp_path.joinpath("models").mkdir()
    cfgmod.save_config(cfg)
    try:
        r = client.post("/api/models/select", headers=auth(admin_token), json={"key": "1.5b"})
        assert r.status_code == 400, r.text
        assert "下载" in r.json()["detail"]
    finally:
        cfg = cfgmod.load_config()
        cfg["models_dir"] = old
        cfgmod.save_config(cfg)


def test_frontend_model_dropdown_contract():
    """模型下拉只能展示已下载模型，且不再出现加载状态后缀。"""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "m.downloaded !== false" in source
    assert "modelState(" not in source
    assert "未加载" not in source
    assert "先在控制台加载" not in source
    assert "/api/models/select" in source
    assert "body: JSON.stringify({ key })" not in source


def test_platform_multimodal_labels():
    from backend.services.platforms import PLATFORMS

    labels = {k: v.get("multimodal", "") for k, v in PLATFORMS.items()}
    assert labels["vllm"] == "多模态"
    assert labels["ollama"] == "多模态（部分）"
    assert labels["lmstudio"] == "多模态（部分）"
    assert labels["llama.cpp"] == ""


def test_frontend_web_toggle_contract():
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'id="webBtn"' in html
    assert "联网" in html
    assert "web: !!web" in js
    assert "renderWebTags" in js
    assert "正在联网检索网页" in js


def test_frontend_chat_deep_link_contract():
    """每一段对话都应能通过 /chat/<id> 直接打开。"""
    from pathlib import Path

    root = Path(__file__).parents[1]
    js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (root / "backend" / "main.py").read_text(encoding="utf-8")
    assert "chatIdFromUrl" in js
    assert "syncChatUrl" in js
    assert 'history.pushState' in js
    assert 'addEventListener("popstate"' in js
    assert 'href="/app.css' in html
    assert 'src="/app.js' in html
    assert '@app.get("/chat/{conversation_id}")' in main


def test_chat_deep_link_route_registered(client):
    r = client.get("/chat/1", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert "/console" in r.headers.get("location", "")


def test_admin_requests_search_by_conversation_id(client, admin_token):
    """调用记录可以按 conversation_id 和会话名称搜索，并返回会话标题。"""
    import asyncio
    import time

    from backend.db import execute

    title = "这是一个用于后台检索的超长会话名称"

    async def insert():
        now = time.time()
        cid = await execute(
            "INSERT INTO conversations(user_id,title,model,system_prompt,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?)", (1, title, "test-model", "", now, now))
        rid = await execute(
            "INSERT INTO requests(trace_id,user_id,conversation_id,provider,model,status,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("uatconv0001", 1, cid, "local", "test-model", "ok", now))
        return cid, rid

    cid, rid = asyncio.run(insert())
    try:
        for q in (str(cid), f"#{cid}", "后台检索的超长会话"):
            r = client.get("/api/admin/requests", params={"q": q}, headers=auth(admin_token))
            assert r.status_code == 200, r.text
            assert r.json()["total"] == 1
            row = r.json()["items"][0]
            assert row["conversation_id"] == cid
            assert row["conversation_title"] == title
            assert row["username"] == "admin"
        # 其他用例可能也留下 admin 的调用记录，这里只验证能搜到目标行。
        r = client.get("/api/admin/requests", params={"q": "admin"}, headers=auth(admin_token))
        assert r.status_code == 200, r.text
        assert any(x["conversation_id"] == cid for x in r.json()["items"])
        detail = client.get(f"/api/admin/requests/{rid}", headers=auth(admin_token))
        assert detail.status_code == 200, detail.text
        req = detail.json()["request"]
        assert req["username"] == "admin"
        assert req["conversation_title"] == title
    finally:
        asyncio.run(execute("DELETE FROM requests WHERE id=?", (rid,)))
        asyncio.run(execute("DELETE FROM conversations WHERE id=?", (cid,)))


def test_lan_api_address_is_not_loopback(monkeypatch):
    from starlette.requests import Request

    from backend.services import netinfo

    monkeypatch.setattr(netinfo, "load_config", lambda: {"port": 9100})
    monkeypatch.setattr(netinfo, "lan_ip", lambda: "192.168.5.38")
    scope = {
        "type": "http", "method": "GET", "scheme": "http", "path": "/api/api-keys/context",
        "query_string": b"", "headers": [(b"host", b"127.0.0.1:9100")],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 9100),
    }
    data = netinfo.detect(Request(scope))
    assert data["scope"] == "local"
    assert data["local_base"] == "http://127.0.0.1:9100/v1"
    assert data["lan_base"] == "http://192.168.5.38:9100/v1"



def test_backup_list_and_existing_download(client, admin_token):
    r = client.get("/api/system/backups", headers=auth(admin_token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    name = items[0]["name"]
    r2 = client.get("/api/system/backups/" + name, headers=auth(admin_token))
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/zip")


def test_migration_archive_has_app_and_data(client, admin_token):
    r = client.post("/api/system/migration", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert {"run.py", "backend/main.py", "data/workbench.db", "data/secret.key", "migrate.ps1", "一键迁移-双击我.bat"}.issubset(names)
        manifest = json.loads(z.read("migration-manifest.json"))
        assert manifest["format"] == "workbench-migration"
        assert manifest["includes_models"] is False
        assert "data/workbench.db" in manifest["files"]
        assert not any("xiaogpt" in name.lower() for name in names)
        cfg = json.loads(z.read("data/config.json"))
        assert "xiaogpt_dir" not in cfg


def test_local_platforms_have_individual_deploy_actions(client, admin_token):
    r = client.get("/api/system/local-deploy", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["github_proxy"] == "auto"
    items = {p["key"]: p for p in data["platforms"]}
    assert {"llama.cpp", "ollama", "vllm", "lmstudio", "custom"}.issubset(items)
    for key, item in items.items():
        assert "install" in item
        assert "action_label" in item
        assert "deployable" in item
        if key != "custom":
            assert item["action"] in ("install", "start", "running", "unsupported", "manual", "guide")
    assert items["custom"]["action"] == "test"


def test_platform_deploy_endpoint_accepts_audit(client, admin_token, monkeypatch):
    from backend.services import platform_deploy
    calls = []

    async def fake_deploy(key, force=False, endpoint=""):
        calls.append((key, force, endpoint))
        return {"ok": True, "msg": "ok"}

    monkeypatch.setattr(platform_deploy, "deploy", fake_deploy)
    r = client.post("/api/system/local-platforms/custom/deploy?endpoint=http%3A%2F%2F127.0.0.1%3A9999",
                    headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    r = client.post("/api/system/local-platforms/nope/deploy", headers=auth(admin_token))
    assert r.status_code == 404


def test_platform_progress_rejects_unknown(client, admin_token):
    r = client.get("/api/system/local-platforms/nope/progress", headers=auth(admin_token))
    assert r.status_code == 404


def test_migration_archive_accepts_legacy_get(client, admin_token):    # 旧版控制台缓存用 GET，新版用 POST；两种都要能生成迁移包。
    r = client.get("/api/system/migration", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")


def test_migration_saves_to_default_folder(client, admin_token):
    r = client.post("/api/system/migration?save=1", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kind"] == "migration"
    assert d["name"].startswith("workbench-migrate-")
    assert d["directory"].endswith("migrations")
    assert d["path"].endswith(d["name"])
    from pathlib import Path
    path = Path(d["path"])
    assert path.exists() and path.stat().st_size > 0
    r2 = client.get(d["download_url"], headers=auth(admin_token))
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/zip")


def test_share_package_has_code_but_no_user_data(client, admin_token):
    r = client.post("/api/system/share?save=1", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kind"] == "share"
    assert d["includes_data"] is False
    assert d["directory"].endswith("shares")
    with zipfile.ZipFile(io.BytesIO(client.get(d["download_url"], headers=auth(admin_token)).content)) as z:
        names = set(z.namelist())
        assert {"backend/main.py", "frontend/index.html", "run.py", "start.ps1", "一键开始-双击我.bat"}.issubset(names)
        for forbidden in ("data/workbench.db", "data/secret.key", "data/config.json", "data/auth_providers.json"):
            assert forbidden not in names
        assert not any(name.startswith(("models/", ".venv/", "llama/", "data/")) for name in names)
        assert not any("xiaogpt" in name.lower() for name in names)
        manifest = json.loads(z.read("share-manifest.json"))
        assert manifest["format"] == "workbench-share"
        assert manifest["includes_data"] is False
        assert manifest["includes_models"] is False


def test_kb_text_search_settings_and_delete(client, admin_token):
    client.cookies.clear()
    r = client.get("/api/kb", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    before = r.json()["count"]

    r = client.post("/api/kb/text", headers=auth(admin_token), data={
        "title": "退款政策 FAQ",
        "content": "退款申请通过后，一般三到五个工作日到账。\n\n超过七天未到账，请联系客服核查。",
    })
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["chunks"] >= 1

    r = client.post("/api/kb/text", headers=auth(admin_token), data={
        "title": "售后会议纪要",
        "content": "会议结论：退款审核时限从 48 小时缩短到 24 小时。",
    })
    assert r.status_code == 200, r.text
    other = r.json()

    r = client.get("/api/kb/search", headers=auth(admin_token), params={"q": "退款几天到账？"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and items[0]["doc_id"] == doc["id"]
    assert items[0]["title"] == "退款政策 FAQ"
    assert "到账" in items[0]["snippet"]
    assert any(x["doc_id"] == other["id"] for x in items)

    r = client.post("/api/kb/settings", headers=auth(admin_token), params={"enabled": "true", "top_k": 3})
    assert r.status_code == 200, r.text
    assert client.get("/api/kb", headers=auth(admin_token)).json()["enabled"] is True

    # 备份 -> 删除 -> 恢复：同名文档在恢复时跳过，避免重复。
    r = client.get("/api/kb/export", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    backup = r.json()
    assert backup["format"] == "workbench-kb-backup"
    assert backup["count"] >= 2
    assert any(d["title"] == "退款政策 FAQ" and "到账" in d["content"] for d in backup["docs"])

    for doc_id in (doc["id"], other["id"]):
        r = client.delete(f"/api/kb/{doc_id}", headers=auth(admin_token))
        assert r.status_code == 200, r.text
    assert client.get("/api/kb", headers=auth(admin_token)).json()["count"] == before

    backup_bytes = json.dumps(backup, ensure_ascii=False).encode()
    r = client.post("/api/kb/restore", headers=auth(admin_token),
                    files={"file": ("kb-backup.json", backup_bytes, "application/json")})
    assert r.status_code == 200, r.text
    restored = r.json()
    assert restored["added"] >= 2
    assert restored["failed"] == 0
    assert client.get("/api/kb", headers=auth(admin_token)).json()["count"] == before + restored["added"]

    # 再恢复一次应全部跳过，不会产生重复文档。
    r = client.post("/api/kb/restore", headers=auth(admin_token),
                    files={"file": ("kb-backup.json", backup_bytes, "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] >= 2

    # 清理：只删本次测试恢复出来的两篇文档。
    rows = client.get("/api/kb", headers=auth(admin_token)).json()["docs"]
    for row in rows:
        if row["title"] in ("退款政策 FAQ", "售后会议纪要"):
            client.delete(f"/api/kb/{row['id']}", headers=auth(admin_token))
    assert client.get("/api/kb", headers=auth(admin_token)).json()["count"] == before
