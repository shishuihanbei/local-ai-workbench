"""多机算力池：节点、模型池和统一模型名。"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


class _FakeOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _json(self, code: int, data: dict):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/v1/models"):
            self._json(200, {"object": "list", "data": [{"id": "fake-model", "object": "model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if not self.path.rstrip("/").endswith("/v1/chat/completions"):
            self._json(404, {"error": "not found"})
            return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for text in ("你", "好"):
                chunk = {"id": "chatcmpl-test", "object": "chat.completion.chunk",
                         "model": "fake-model",
                         "choices": [{"index": 0, "delta": {"content": text}}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            done = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "model": "fake-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2}}
            self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
            return
        self._json(200, {
            "id": "chatcmpl-test", "object": "chat.completion", "model": "fake-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        })


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_cluster_node_and_pool_crud(client, admin_token):
    headers = auth(admin_token)
    r = client.post("/api/admin/cluster/nodes", headers=headers, json={
        "name": "测试机-A",
        "base_url": "192.168.1.40:11434",
        "weight": 2,
        "max_concurrency": 3,
        "note": "pytest",
    })
    assert r.status_code == 200, r.text
    node = r.json()["node"]
    assert node["base_url"] == "http://192.168.1.40:11434/v1"
    assert node["has_key"] is False
    assert node["weight"] == 2

    r = client.post("/api/admin/cluster/pools", headers=headers, json={
        "name": "pytest-pool",
        "strategy": "weighted_least",
        "retries": 1,
        "members": [{"node_id": node["id"], "remote_model": "qwen3:8b", "weight": 2}],
    })
    assert r.status_code == 200, r.text
    pool = r.json()["pool"]
    assert pool["name"] == "pytest-pool"
    assert pool["members"][0]["remote_model"] == "qwen3:8b"

    r = client.get("/api/admin/cluster", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["stats"]["nodes"] >= 1
    assert any(p["name"] == "pytest-pool" for p in data["pools"])

    key = client.post("/api/api-keys", headers=headers, json={"name": "cluster-pytest"}).json()["key"]
    r = client.get("/v1/models", headers={"Authorization": "Bearer " + key})
    assert r.status_code == 200, r.text
    ids = {m["id"] for m in r.json()["data"]}
    assert "pytest-pool" in ids

    r = client.get("/api/models", headers=headers)
    assert r.status_code == 200, r.text
    assert any(m["key"] == "pytest-pool" and m["loaded"] for m in r.json()["items"])

    r = client.patch(f"/api/admin/cluster/pools/{pool['id']}", headers=headers, json={
        "strategy": "round_robin",
        "members": [{"node_id": node["id"], "remote_model": "qwen3:8b", "weight": 3}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["pool"]["strategy"] == "round_robin"
    assert r.json()["pool"]["members"][0]["weight"] == 3

    r = client.delete(f"/api/admin/cluster/pools/{pool['id']}", headers=headers)
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/admin/cluster/nodes/{node['id']}", headers=headers)
    assert r.status_code == 200, r.text
    r = client.get("/api/admin/cluster", headers=headers)
    assert not any(n["name"] == "测试机-A" for n in r.json()["nodes"])


def test_cluster_pool_routes_to_openai_compatible_node(client, admin_token):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    headers = auth(admin_token)
    node = client.post("/api/admin/cluster/nodes", headers=headers, json={
        "name": "pytest-fake-node",
        "base_url": f"http://127.0.0.1:{port}/v1",
    }).json()["node"]
    r = client.post(f"/api/admin/cluster/nodes/{node['id']}/test", headers=headers)
    assert r.status_code == 200 and r.json()["ok"], r.text

    pool = client.post("/api/admin/cluster/pools", headers=headers, json={
        "name": "pytest-fake-pool",
        "retries": 1,
        "members": [{"node_id": node["id"], "remote_model": "fake-model"}],
    }).json()["pool"]
    key = client.post("/api/api-keys", headers=headers, json={"name": "cluster-route-pytest"}).json()["key"]
    api_headers = {"Authorization": "Bearer " + key}
    try:
        r = client.post("/v1/chat/completions", headers=api_headers, json={
            "model": "pytest-fake-pool",
            "messages": [{"role": "user", "content": "测试"}],
            "stream": False,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["model"] == "pytest-fake-pool"
        assert data["choices"][0]["message"]["content"] == "你好"

        with client.stream("POST", "/v1/chat/completions", headers=api_headers, json={
            "model": "pytest-fake-pool",
            "messages": [{"role": "user", "content": "测试"}],
            "stream": True,
        }) as response:
            assert response.status_code == 200
            body = "\n".join(response.iter_lines())
        assert "pytest-fake-pool" in body
        assert "你" in body and "好" in body
        assert "[DONE]" in body

        with client.stream("POST", "/api/chat/stream", headers=auth(admin_token), json={
            "model": "pytest-fake-pool",
            "message": "网页聊天也走池",
        }) as response:
            assert response.status_code == 200, response.text
            chat_body = "\n".join(response.iter_lines())
        assert '"type": "delta"' in chat_body or '"type":"delta"' in chat_body
    finally:
        import asyncio
        import time
        from backend.db import execute
        time.sleep(1.0)

        async def cleanup_logs():
            await execute("DELETE FROM requests")
            await execute("DELETE FROM spans")

        asyncio.run(cleanup_logs())
        client.delete(f"/api/admin/cluster/pools/{pool['id']}", headers=headers)
        client.delete(f"/api/admin/cluster/nodes/{node['id']}", headers=headers)
        server.shutdown()
        thread.join(timeout=2)
