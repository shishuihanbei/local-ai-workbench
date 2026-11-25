"""用户组、管理员角色细粒度权限、每用户 Token 配额。"""
from __future__ import annotations

import base64

from tests.conftest import auth


def _create_group(client, token, name="测试组"):
    r = client.post("/api/users/groups", headers=auth(token),
                    json={"name": name, "description": "pytest"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_role(client, token, name, permissions):
    r = client.post("/api/users/roles", headers=auth(token),
                    json={"name": name, "permissions": permissions})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_groups_roles_and_restricted_admin(client, admin_token):
    gid = _create_group(client, admin_token, "研发组")
    rid = _create_role(client, admin_token, "只读 IT", ["overview", "users"])

    r = client.post("/api/users", headers=auth(admin_token), json={
        "username": "restricted-admin", "password": "Restricted-pass-2026",
        "role": "admin", "group_id": gid, "admin_role_id": rid,
        "daily_token_limit": 1000, "monthly_token_limit": 20000,
    })
    assert r.status_code == 200, r.text
    uid = r.json()["id"]

    users = client.get("/api/users", headers=auth(admin_token)).json()["items"]
    item = next(x for x in users if x["id"] == uid)
    assert item["group_name"] == "研发组"
    assert item["admin_role_name"] == "只读 IT"
    assert item["daily_token_limit"] == 1000

    login = client.post("/api/auth/login", json={
        "username": "restricted-admin", "password": "Restricted-pass-2026"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    assert client.get("/api/admin/overview", headers=auth(token)).status_code == 200
    assert client.get("/api/users", headers=auth(token)).status_code == 200
    assert client.get("/api/admin/providers", headers=auth(token)).status_code == 403
    assert client.get("/api/admin/audit", headers=auth(token)).status_code == 403
    me = client.get("/api/auth/me", headers=auth(token)).json()["user"]
    assert set(me["admin_permissions"]) == {"overview", "users"}

    # 组和角色可改可删；删组会清空成员分组
    r = client.patch(f"/api/users/groups/{gid}", headers=auth(admin_token),
                     json={"name": "研发组-改", "description": "updated"})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/users/roles/{rid}", headers=auth(admin_token),
                     json={"permissions": ["overview", "users", "audit"]})
    assert r.status_code == 200, r.text
    assert client.get("/api/admin/audit", headers=auth(token)).status_code == 200

    # 角色仍被绑定，删除应被拒绝
    assert client.delete(f"/api/users/roles/{rid}", headers=auth(admin_token)).status_code == 400
    assert client.delete(f"/api/users/groups/{gid}", headers=auth(admin_token)).status_code == 200
    users = client.get("/api/users", headers=auth(admin_token)).json()["items"]
    assert next(x for x in users if x["id"] == uid)["group_id"] is None


def test_daily_token_quota_blocks_chat(client, admin_token):
    r = client.post("/api/users", headers=auth(admin_token), json={
        "username": "quota-user", "password": "Quota-pass-2026", "role": "user",
        "allowed_models": ["*"], "daily_token_limit": 1, "monthly_token_limit": 0,
    })
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    r = client.post("/api/admin/database/query", headers=auth(admin_token), json={
        "sql": f"INSERT INTO requests(trace_id,user_id,total_tokens,created_at) "
               f"VALUES('pytest-quota',{uid},5,strftime('%s','now'))",
        "allow_write": True,
    })
    assert r.status_code == 200, r.text

    login = client.post("/api/auth/login", json={
        "username": "quota-user", "password": "Quota-pass-2026"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    r = client.post("/api/chat/stream", headers=auth(token),
                    json={"message": "你好", "model": "qwen2.5"})
    assert r.status_code == 429, r.text
    assert "配额" in r.text

    users = client.get("/api/users", headers=auth(admin_token)).json()["items"]
    item = next(x for x in users if x["id"] == uid)
    assert item["today_tokens"] >= 5


def test_department_tree_and_import_export(client, admin_token):
    gid = _create_group(client, admin_token, "部门根")
    child = client.post("/api/users/groups", headers=auth(admin_token), json={
        "name": "子部门", "description": "tree", "parent_id": gid}).json()["id"]
    groups = client.get("/api/users/groups", headers=auth(admin_token)).json()["items"]
    assert next(g for g in groups if g["id"] == child)["parent_name"] == "部门根"
    # 不能把父部门移动到自己的子部门下
    r = client.patch(f"/api/users/groups/{gid}", headers=auth(admin_token),
                     json={"name": "部门根", "parent_id": child})
    assert r.status_code == 400 and "下级" in r.text

    r = client.post("/api/users/import", headers=auth(admin_token), json={
        "text": "username,password,role,group,allowed_models,daily_token_limit,monthly_token_limit\n"
                "import-a,Import-pass-2026,user,子部门,*,100,2000\n"
                "import-b,Import-pass-2026,user,子部门,,\n"
                "import-a,Import-pass-2026,user,子部门,,\n",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 2 and data["skipped"] == 1
    users = client.get("/api/users", headers=auth(admin_token)).json()["items"]
    assert any(u["username"] == "import-a" and u["daily_token_limit"] == 100 for u in users)

    exp = client.get("/api/users/export", headers=auth(admin_token))
    assert exp.status_code == 200
    assert "username,role,group" in exp.text
    assert "import-a" in exp.text


def test_org_branding_watermark_and_permission(client, admin_token):
    r = client.put("/api/admin/org", headers=auth(admin_token), json={
        "org_name": "测试科技", "org_short_name": "测试", "org_domain": "test.local",
        "org_industry": "软件", "org_size": "10-20 人", "org_contact_name": "张三",
        "org_contact_email": "a@test.local", "watermark_enabled": True,
        "watermark_text": "{user} · {org} · 内部资料",
        "brand_tagline": "Test AI", "brand_login_title": "测试工作台",
        "brand_login_lead": "这是测试说明", "brand_login_foot": "仅用于测试",
        "brand_auth_subtitle": "请登录测试账号", "brand_primary": "#123456",
        "brand_icp": "测试ICP备123号", "brand_icp_url": "https://beian.miit.gov.cn/",
        "brand_police": "测试公网安备 123号", "brand_police_url": "https://beian.mps.gov.cn/",
        "brand_copyright": "© 2026 测试科技",
    })
    assert r.status_code == 200, r.text
    state = client.get("/api/auth/state").json()
    assert state["branding"]["org_name"] == "测试科技"
    assert state["branding"]["watermark_enabled"] is True
    assert state["branding"]["brand_login_title"] == "测试工作台"
    assert state["branding"]["brand_icp"] == "测试ICP备123号"
    assert state["branding"]["brand_primary"] == "#123456"

    org = client.get("/api/admin/org", headers=auth(admin_token)).json()
    assert org["brand_icp"] == "测试ICP备123号"
    assert org["brand_copyright"] == "© 2026 测试科技"

    assert client.get("/api/branding/logo").status_code == 404
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
    upload = client.post("/api/admin/org/logo", headers=auth(admin_token),
                         files={"file": ("logo.png", png, "image/png")})
    assert upload.status_code == 200, upload.text
    logo_url = upload.json()["url"]
    assert logo_url.startswith("/api/branding/logo?v=")
    got = client.get(logo_url)
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/png")
    assert client.get("/api/auth/state").json()["branding"]["brand_logo_url"] == logo_url

    bad = client.post("/api/admin/org/logo", headers=auth(admin_token),
                      files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert bad.status_code == 400
    assert "PNG" in bad.json()["detail"]

    assert client.delete("/api/admin/org/logo", headers=auth(admin_token)).status_code == 200
    assert client.get("/api/branding/logo").status_code == 404

    rid = _create_role(client, admin_token, "企业管理员", ["org"])
    r = client.post("/api/users", headers=auth(admin_token), json={
        "username": "org-admin", "password": "Org-admin-pass-2026",
        "role": "admin", "admin_role_id": rid,
    })
    assert r.status_code == 200, r.text
    login = client.post("/api/auth/login", json={"username": "org-admin", "password": "Org-admin-pass-2026"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert client.get("/api/admin/org", headers=auth(token)).status_code == 200
    assert client.get("/api/admin/overview", headers=auth(token)).status_code == 403
