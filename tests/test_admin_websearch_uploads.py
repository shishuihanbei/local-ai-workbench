"""控制台联网检索与附件重新解析接口回归。"""
from __future__ import annotations

import asyncio
import time


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_websearch_controls_and_test_endpoint(client, admin_token, monkeypatch):
    from backend.services import websearch

    r = client.get("/api/system/websearch", headers=auth(admin_token))
    assert r.status_code == 200, r.text
    initial = r.json()
    assert "enabled" in initial and "max_sources" in initial and "max_pages" in initial

    try:
        r = client.put("/api/system/websearch", headers=auth(admin_token), json={
            "enabled": False, "max_sources": 3, "max_pages": 1,
        })
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert cfg["enabled"] is False
        assert cfg["max_sources"] == 3
        assert cfg["max_pages"] == 1

        r = client.post("/api/system/websearch/test", headers=auth(admin_token),
                        json={"query": "测试检索"})
        assert r.status_code == 400
        assert "已关闭" in r.json()["detail"]

        async def fake_research(query: str, limit: int | None = None,
                                pages: int | None = None, prefer_news: bool = False):
            return {"query": query, "sources": [
                {"title": "测试来源", "url": "https://example.com/a", "snippet": "摘要"}],
                "prompt": "", "error": ""}

        monkeypatch.setattr(websearch, "research", fake_research)
        r = client.put("/api/system/websearch", headers=auth(admin_token), json={
            "enabled": True, "max_sources": 4, "max_pages": 2,
        })
        assert r.status_code == 200

        r = client.post("/api/system/websearch/test", headers=auth(admin_token),
                        json={"query": "测试检索", "max_sources": 2, "max_pages": 1})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["sources"][0]["url"] == "https://example.com/a"
        assert data["query"] == "测试检索"

        r = client.post("/api/system/websearch/cache/clear", headers=auth(admin_token))
        assert r.status_code == 200
    finally:
        client.put("/api/system/websearch", headers=auth(admin_token), json={
            "enabled": True, "max_sources": 5, "max_pages": 2,
        })


def test_upload_records_text_and_reparse_job(client, admin_token):
    from backend.services import attachments

    async def make_file(name: str, raw: bytes):
        return await attachments.save(1, name, "text/plain", raw)

    text_file = asyncio.run(make_file("控制台解析测试.txt", "第一行\n第二行".encode("utf-8")))
    empty_file = asyncio.run(make_file("控制台空文件.txt", b""))

    r = client.get("/api/admin/uploads?status=parsed&q=控制台解析测试",
                   headers=auth(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    assert any(x["id"] == text_file["id"] for x in data["items"])
    assert data["engine"]["engine"] == "RapidOCR"
    assert data["stats"]["empty"] >= 1
    assert data["stats"]["errors"] == 0

    r = client.get(f"/api/admin/uploads/{text_file['id']}/text", headers=auth(admin_token))
    assert r.status_code == 200
    assert "第一行" in r.json()["text"]

    r = client.get(f"/api/admin/uploads/{empty_file['id']}/text", headers=auth(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == ""
    assert body["parse_error"]

    r = client.post("/api/admin/uploads/reparse", headers=auth(admin_token),
                    json={"ids": [text_file["id"]], "only_empty": False})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]

    deadline = time.time() + 8
    while time.time() < deadline:
        job = client.get(f"/api/admin/uploads/jobs/{job_id}", headers=auth(admin_token)).json()
        if job["status"] == "done":
            break
        time.sleep(0.2)
    assert job["status"] == "done"
    assert job["done"] == 1
    assert job["ok"] == 1

    r = client.get(f"/api/admin/uploads/{text_file['id']}/file", headers=auth(admin_token))
    assert r.status_code == 200
    assert "第一行" in r.text

    r = client.get("/api/admin/uploads?status=empty&q=控制台空文件",
                   headers=auth(admin_token))
    assert r.status_code == 200
    assert any(x["id"] == empty_file["id"] for x in r.json()["items"])

    r = client.get("/api/admin/uploads?status=error&q=控制台空文件",
                   headers=auth(admin_token))
    assert r.status_code == 200
    assert not any(x["id"] == empty_file["id"] for x in r.json()["items"])

    r = client.post("/api/admin/uploads/reparse", headers=auth(admin_token),
                    json={"ids": [empty_file["id"]], "only_empty": False})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    deadline = time.time() + 8
    while time.time() < deadline:
        job = client.get(f"/api/admin/uploads/jobs/{job_id}", headers=auth(admin_token)).json()
        if job["status"] == "done":
            break
        time.sleep(0.2)
    assert job["status"] == "done"
    assert job["ok"] == 1
    assert job["empty"] == 1
    assert job["failed"] == 0
