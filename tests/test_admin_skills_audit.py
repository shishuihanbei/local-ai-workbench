"""自定义技能与管理员审计日志。"""
from __future__ import annotations


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_custom_skill_lifecycle_and_audit(client, admin_token):
    h = auth(admin_token)
    created = client.post("/api/admin/skills", headers=h, json={
        "name": "周报整理",
        "hint": "按进展 / 风险 / 下周计划整理",
        "icon": "list",
        "prompt": "请按进展、风险、下周计划三部分整理，保留数字和负责人。",
        "enabled": True,
        "sort": 5,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["id"]

    public = client.get("/api/chat/skills", headers=h).json()["items"]
    assert any(s["id"] == f"custom_{sid}" and s["name"] == "周报整理" for s in public)
    assert any(s["id"] == "summary" for s in public)

    from backend.services import skills
    skills.reload_custom()
    assert skills.get(f"custom_{sid}")["name"] == "周报整理"

    disabled = client.patch(f"/api/admin/skills/{sid}", headers=h, json={"enabled": False})
    assert disabled.status_code == 200, disabled.text
    public2 = client.get("/api/chat/skills", headers=h).json()["items"]
    assert all(s["id"] != f"custom_{sid}" for s in public2)

    audit = client.get("/api/admin/audit", headers=h, params={"action": "skill."})
    assert audit.status_code == 200, audit.text
    actions = [row["action"] for row in audit.json()["items"]]
    assert "skill.create" in actions
    assert "skill.update" in actions

    deleted = client.delete(f"/api/admin/skills/{sid}", headers=h)
    assert deleted.status_code == 200, deleted.text
    public3 = client.get("/api/chat/skills", headers=h).json()["items"]
    assert all(s["id"] != f"custom_{sid}" for s in public3)


def test_skill_name_validation(client, admin_token):
    h = auth(admin_token)
    dup = client.post("/api/admin/skills", headers=h, json={
        "name": "总结提炼",
        "prompt": "x",
    })
    assert dup.status_code == 400
    bad_icon = client.post("/api/admin/skills", headers=h, json={
        "name": "图标测试",
        "prompt": "x",
        "icon": "not-exist",
    })
    assert bad_icon.status_code == 400
