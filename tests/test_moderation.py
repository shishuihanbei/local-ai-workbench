"""内容安全：词库、策略、输入拦截、流式跨块替换与命中记录。"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _FakeOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _json(self, data: dict):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._json({"object": "list", "data": [{"id": "fake-model", "object": "model"}]})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for text in ("你", "好"):
                chunk = {"id": "chatcmpl-test", "object": "chat.completion.chunk",
                         "model": "fake-model",
                         "choices": [{"index": 0, "delta": {"content": text}}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self._json({
            "id": "chatcmpl-test", "object": "chat.completion", "model": "fake-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        })


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _restore_cfg(old: dict, keys: tuple[str, ...]) -> None:
    from backend import config as cfgmod

    cfg = cfgmod.load_config()
    for key in keys:
        cfg[key] = old.get(key)
    cfgmod.save_config(cfg)


@pytest.fixture()
def moderation_cfg():
    from backend import config as cfgmod

    keys = ("moderation_enabled", "moderation_input_action", "moderation_output_action",
            "moderation_replace", "moderation_min_chars")
    cfg = cfgmod.load_config()
    old = {k: cfg.get(k) for k in keys}
    yield
    _restore_cfg(old, keys)
    from backend.services import moderation

    moderation.invalidate()


def test_moderation_tables_and_word_crud(client, admin_token):
    headers = auth(admin_token)
    r = client.get("/api/admin/moderation", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"enabled", "input_action", "output_action", "replace_with", "min_chars"}.issubset(
        body["settings"])
    assert isinstance(body["words"], list)

    word = "pytest敏感词A"
    r = client.post("/api/admin/moderation/words", headers=headers,
                    json={"word": word, "category": "pytest", "note": "自动化测试"})
    assert r.status_code == 200, r.text
    r = client.post("/api/admin/moderation/words", headers=headers, json={"word": word})
    assert r.status_code == 400

    r = client.post("/api/admin/moderation/words/bulk", headers=headers,
                    json={"text": "pytest批量B\npytest批量C", "category": "pytest-bulk"})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2

    listed = client.get("/api/admin/moderation?word_q=pytest", headers=headers).json()["words"]
    assert {w["word"] for w in listed} >= {word, "pytest批量B", "pytest批量C"}
    target = next(w for w in listed if w["word"] == word)
    r = client.patch(f"/api/admin/moderation/words/{target['id']}", headers=headers,
                     json={"enabled": False})
    assert r.status_code == 200, r.text
    listed = client.get("/api/admin/moderation?word_q=pytest", headers=headers).json()["words"]
    assert next(w for w in listed if w["id"] == target["id"])["enabled"] == 0

    for w in listed:
        r = client.delete(f"/api/admin/moderation/words/{w['id']}", headers=headers)
        assert r.status_code == 200, r.text


def test_chat_input_block_and_hit(client, admin_token, moderation_cfg):
    headers = auth(admin_token)
    word = "pytest输入泄露词"
    client.post("/api/admin/moderation/words", headers=headers, json={"word": word})
    r = client.put("/api/admin/moderation", headers=headers, json={
        "enabled": True, "input_action": "block", "output_action": "replace",
        "replace_with": "***", "min_chars": 1,
    })
    assert r.status_code == 200, r.text

    r = client.post("/api/chat/stream", headers=headers, json={
        "message": f"这句话包含 {word}，应该被拦下", "model": "pytest-model",
    })
    assert r.status_code == 400, r.text
    assert "敏感词" in r.json()["detail"]

    data = client.get("/api/admin/moderation?direction=input", headers=headers).json()
    assert any(word in h["words"] for h in data["hits"])
    assert data["hits"][0]["action"] == "block"


def test_input_replace_and_output_guard(client, admin_token, moderation_cfg):
    from backend.services import moderation

    headers = auth(admin_token)
    word = "pytest替换词"
    client.post("/api/admin/moderation/words", headers=headers, json={"word": word})
    client.put("/api/admin/moderation", headers=headers, json={
        "enabled": True, "input_action": "replace", "output_action": "replace",
        "replace_with": "【已屏蔽】", "min_chars": 1,
    })
    guard = asyncio.run(moderation.guard_input(
        f"前文 {word} 后文", user={"id": 1, "username": "admin"}, model="pytest-model"))
    assert guard["matches"] == [word]
    assert word not in guard["text"]
    assert "【已屏蔽】" in guard["text"]

    out = asyncio.run(moderation.guard_output(
        f"模型回复里有 {word}", user={"id": 1, "username": "admin"}, model="pytest-model"))
    assert out["matches"] == [word]
    assert word not in out["text"]
    assert "【已屏蔽】" in out["text"]


def test_stream_filter_cross_chunk_replace_and_block():
    from backend.services.moderation import StreamFilter

    word = "跨块敏感词"
    flt = StreamFilter(action="replace", words=[word], replacement="***")
    chunks = ["开头跨", "块敏", "感词结尾"]
    out = "".join(flt.feed(c) for c in chunks) + flt.flush()
    assert word not in out
    assert "***" in out
    assert out == "开头***结尾"

    blocked = StreamFilter(action="block", words=[word])
    assert blocked.feed("开头跨") == ""
    assert blocked.feed("块敏") in ("", "开")
    assert blocked.feed("感词结尾") == ""
    assert blocked.blocked is True
    assert blocked.matched == [word]


def test_openai_pool_output_replace_nonstream_and_stream(client, admin_token, moderation_cfg):
    headers = auth(admin_token)
    word = "你好"
    client.post("/api/admin/moderation/words", headers=headers, json={"word": word})
    client.put("/api/admin/moderation", headers=headers, json={
        "enabled": True, "input_action": "block", "output_action": "replace",
        "replace_with": "***", "min_chars": 1,
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    node = client.post("/api/admin/cluster/nodes", headers=headers, json={
        "name": "pytest-moderation-node", "base_url": f"http://127.0.0.1:{port}/v1",
    }).json()["node"]
    pool = client.post("/api/admin/cluster/pools", headers=headers, json={
        "name": "pytest-moderation-pool", "retries": 1,
        "members": [{"node_id": node["id"], "remote_model": "fake-model"}],
    }).json()["pool"]
    key = client.post("/api/api-keys", headers=headers, json={
        "name": "moderation-output-pytest"}).json()["key"]
    api_headers = {"Authorization": "Bearer " + key}
    try:
        r = client.post("/v1/chat/completions", headers=api_headers, json={
            "model": "pytest-moderation-pool",
            "messages": [{"role": "user", "content": "测试输出"}],
            "stream": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["choices"][0]["message"]["content"] == "***"

        with client.stream("POST", "/v1/chat/completions", headers=api_headers, json={
            "model": "pytest-moderation-pool",
            "messages": [{"role": "user", "content": "测试流式输出"}],
            "stream": True,
        }) as response:
            assert response.status_code == 200
            body = "\n".join(response.iter_lines())
        assert word not in body
        assert "***" in body
        data = client.get("/api/admin/moderation?direction=output", headers=headers).json()
        assert any(word in h["words"] for h in data["hits"])
    finally:
        time.sleep(0.5)
        from backend.db import execute

        asyncio.run(execute("DELETE FROM requests"))
        asyncio.run(execute("DELETE FROM spans"))
        client.delete(f"/api/admin/cluster/pools/{pool['id']}", headers=headers)
        client.delete(f"/api/admin/cluster/nodes/{node['id']}", headers=headers)
        server.shutdown()
        thread.join(timeout=2)


def test_moderation_console_contract():
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "backend" / "console" / "index.html").read_text(encoding="utf-8")
    js = "".join(p.read_text(encoding="utf-8") for p in sorted((root / "backend" / "console").rglob("*.js")))
    assert 'id="pane-moderation"' in html
    assert 'data-tab="moderation"' in html
    assert 'id="modWordRows"' in html
    assert 'id="modHitRows"' in html
    assert 'moderation: "moderation"' in js
    assert "loadModerationPage" in js
