"""提示词中心回归：资产完整、版本留痕、恢复默认、拼装预览与热更新。"""
from __future__ import annotations


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_prompt_assets_are_registered(client, admin_token):
    r = client.get("/api/admin/prompts", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["revision"] >= 1
    assert data["total"] >= 32
    counts = data["counts"]
    assert counts["core"] == 1
    assert counts["skill"] >= 6
    assert counts["plugin"] == 10
    assert counts["format"] == 6
    assert counts["workbench"] == 9

    items = {x["key"]: x for x in data["items"]}
    assert "core.system" in items
    assert "skill.summary" in items
    assert "format.md" in items
    assert "function.memory_rules" in items
    assert all(x["kind"] for x in data["items"])
    assert data["pipeline"][0]["key"] == "core.system"
    assert data["pipeline"][-1]["key"] == "function.web_rules_general"


def test_prompt_detail_and_workbench_catalog(client, admin_token):
    r = client.get("/api/admin/prompts/workbench.teacher", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["kind"] == "workbench"
    assert item["meta"]["template_id"] == "teacher"
    assert item["versions"] == []
    import json
    tpl = json.loads(item["content"])
    assert tpl["id"] == "teacher"
    assert len(tpl["quick"]) == 8

    r = client.get("/api/workbench/catalog", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    catalog = r.json()
    assert len(catalog["items"]) == 9
    assert all(len(t["quick"]) >= 1 for t in catalog["items"])
    assert {t["id"] for t in catalog["items"]} == {
        "teacher", "finance", "marketing", "design", "writing",
        "formal", "media", "doctor", "game",
    }


def test_prompt_save_version_preview_reset_hot_reload(client, admin_token):
    from backend.services import docgen

    before = client.get("/api/admin/prompts/format.md", headers=auth(admin_token)).json()
    original = before["content"]
    r = client.put("/api/admin/prompts/format.md", headers=auth(admin_token), json={
        "content": original + "\nPYTEST_MARK_2026",
    })
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["revision"] > 0
    assert "PYTEST_MARK_2026" in docgen.prompt_hint("md")

    detail = client.get("/api/admin/prompts/format.md", headers=auth(admin_token)).json()
    assert detail["overridden"]
    assert detail["content"].endswith("PYTEST_MARK_2026")
    assert detail["versions"][0]["version"] == 1

    r = client.post("/api/admin/prompts/preview", headers=auth(admin_token), json={
        "output_format": "md",
        "use_kb": True,
        "use_memory": True,
        "use_web": True,
    })
    assert r.status_code == 200, r.text
    preview = r.json()
    assert "基础人格" in preview["text"]
    assert "知识库引用" in preview["text"]
    assert "长期记忆" in preview["text"]
    assert "联网检索" in preview["text"]
    assert preview["tokens"] > 0

    r = client.post("/api/admin/prompts/format.md/reset", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    assert "PYTEST_MARK_2026" not in docgen.prompt_hint("md")
    after = client.get("/api/admin/prompts/format.md", headers=auth(admin_token)).json()
    assert after["content"] == original
    assert not after["overridden"]
    assert len(after["versions"]) >= 2


def test_prompt_restore_creates_new_version(client, admin_token):
    item = client.get("/api/admin/prompts/skill.polish", headers=auth(admin_token)).json()
    original = item["content"]
    r = client.put("/api/admin/prompts/skill.polish", headers=auth(admin_token), json={
        "content": original + "\n先给结论。",
    })
    assert r.status_code == 200, r.text
    r = client.put("/api/admin/prompts/skill.polish", headers=auth(admin_token), json={
        "content": original + "\n先给结论。\n再给依据。",
    })
    assert r.status_code == 200, r.text
    versions = client.get(
        "/api/admin/prompts/skill.polish", headers=auth(admin_token)).json()["versions"]
    first_version = versions[-1]["version"]
    r = client.post(
        f"/api/admin/prompts/skill.polish/restore/{first_version}",
        headers=auth(admin_token),
    )
    assert r.status_code == 200, r.text
    latest = client.get("/api/admin/prompts/skill.polish", headers=auth(admin_token)).json()
    assert latest["content"].endswith("先给结论。")
    assert len(latest["versions"]) >= 3


def test_prompt_admin_requires_login(client):
    client.cookies.clear()
    r = client.get("/api/admin/prompts")
    assert r.status_code == 401
