"""前台功能开关与图标库回归。"""
from __future__ import annotations

import base64
import re
from pathlib import Path


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


PNG = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"0" * 64
).decode()


def test_front_catalog_defaults(client, admin_token):
    r = client.get("/api/admin/front-features", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["revision"] >= 1
    assert len(data["items"]) == 16
    assert len(data["groups"]) == 4
    assert len(data["presets"]) >= 16
    keys = {x["key"] for x in data["items"]}
    assert {"skills", "web", "agent_tools", "library", "kb", "memory", "workbench", "schedule", "files",
            "collab", "desk", "api_access", "data_export"} <= keys
    assert all(x["name"] and x["description"] for x in data["items"])


def test_front_public_filters_and_workbench_dependency(client, admin_token):
    catalog = client.get("/api/admin/front-features", headers=auth(admin_token)).json()
    items = [{
        "key": x["key"], "enabled": x["enabled"], "icon_key": x["icon_key"],
        "icon_tone": x["icon_tone"], "icon_id": x["icon_id"],
    } for x in catalog["items"]]
    for x in items:
        if x["key"] == "workbench":
            x["enabled"] = False
    r = client.put("/api/admin/front-features", headers=auth(admin_token), json={"items": items})
    assert r.status_code == 200, r.text
    data = r.json()
    by_key = {x["key"]: x for x in data["items"]}
    assert by_key["workbench"]["visible"] is False
    assert by_key["schedule"]["visible"] is False
    assert by_key["schedule"]["blocked_by"] == "workbench"
    assert by_key["files"]["blocked_by"] == "workbench"

    public = client.get("/api/front/features", headers=auth(admin_token)).json()
    public_keys = {x["key"] for x in public["items"]}
    assert "workbench" not in public_keys
    assert "schedule" not in public_keys
    assert "files" not in public_keys
    assert "skills" in public_keys

    for x in items:
        if x["key"] == "workbench":
            x["enabled"] = True
    r = client.put("/api/admin/front-features", headers=auth(admin_token), json={"items": items})
    assert r.status_code == 200, r.text


def test_front_icon_upload_apply_delete(client, admin_token):
    r = client.post("/api/admin/front-icons", headers=auth(admin_token),
                    json={"name": "测试星标", "data": PNG})
    assert r.status_code == 200, r.text
    icon = r.json()
    iid = icon["id"]

    catalog = client.get("/api/admin/front-features", headers=auth(admin_token)).json()
    items = [{
        "key": x["key"], "enabled": x["enabled"], "icon_key": x["icon_key"],
        "icon_tone": x["icon_tone"], "icon_id": x["icon_id"],
    } for x in catalog["items"]]
    for x in items:
        if x["key"] == "docgen":
            x["icon_id"] = iid
            x["icon_tone"] = "amber"
    r = client.put("/api/admin/front-features", headers=auth(admin_token), json={"items": items})
    assert r.status_code == 200, r.text
    after = r.json()
    lib = next(x for x in after["items"] if x["key"] == "docgen")
    assert lib["icon_id"] == iid
    assert lib["icon_tone"] == "amber"
    assert lib["icon_data"].startswith("data:image/png;base64,")

    public = client.get("/api/front/features", headers=auth(admin_token)).json()
    plib = next(x for x in public["items"] if x["key"] == "docgen")
    assert plib["icon_data"].startswith("data:image/png;base64,")

    r = client.delete(f"/api/admin/front-icons/{iid}", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["icons"] == []
    after_delete = client.get("/api/admin/front-features", headers=auth(admin_token)).json()
    lib2 = next(x for x in after_delete["items"] if x["key"] == "docgen")
    assert lib2["icon_id"] == 0
    assert lib2["icon_data"] == ""


def test_front_frontend_mount_points_cover_all_features():
    root = Path(__file__).resolve().parents[1]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (root / "frontend" / "app.css").read_text(encoding="utf-8")
    app = "".join(p.read_text(encoding="utf-8") for p in sorted((root / "frontend").glob("*.js")))
    expected = {"skills", "web", "agent_tools", "docgen", "attach", "agent", "library", "kb", "memory",
                "workbench", "schedule", "files", "collab", "desk", "api_access", "data_export"}
    mounted = set(re.findall(r'data-front="([^"]+)"', html))
    assert expected <= mounted
    assert "[data-front-off]" in css
    assert "front-icon-slot" in css
    assert "FRONT_TAB_FEATURE" in app
    assert "applyFrontFeatures" in app
