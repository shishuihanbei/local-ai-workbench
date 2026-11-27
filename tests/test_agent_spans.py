"""Agent 工具轨迹写入 spans 的回归测试（不依赖真实模型）。"""
from __future__ import annotations

import json

from tests.conftest import auth


def _fake_agent_result():
    return {
        "content": "根据知识库，报销走线上流程。",
        "reasoning": "",
        "usage": {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20},
        "trace": [{
            "tool": "search_knowledge_base",
            "turn": 1,
            "arguments": {"query": "报销流程"},
            "status": "ok",
            "summary": "命中 2 条片段：报销制度第 3 条…",
            "count": 2,
            "sources": [{"title": "报销制度", "url": "http://kb.local/doc/3"}],
            "error": "",
            "dur_ms": 42,
        }],
        "messages": [],
    }


def _meta_of(body: str) -> dict:
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[5:].strip())
        except Exception:
            continue
        if obj.get("type") == "meta":
            return obj
    raise AssertionError("SSE 里没有 meta 事件：" + body[:400])


def test_chat_writes_tool_spans_and_lists_them(client, admin_token, monkeypatch):
    from backend import config as cfgmod
    from backend.routers import chat as chat_mod

    cfg = cfgmod.load_config()
    old = {k: cfg.get(k) for k in ("kb_enabled", "agent_mode_enabled", "agent_max_turns")}
    cfg["kb_enabled"] = True
    cfg["agent_mode_enabled"] = True
    cfg["agent_max_turns"] = 2
    cfgmod.save_config(cfg)

    calls: list[dict] = []

    async def fake_run_agent(**kwargs):
        calls.append(kwargs)
        return _fake_agent_result()

    monkeypatch.setattr(chat_mod.agent_runtime, "run_agent", fake_run_agent)
    try:
        with client.stream("POST", "/api/chat/stream", headers=auth(admin_token),
                           json={"message": "公司报销怎么走？", "agent_mode": True}) as r:
            assert r.status_code == 200, r.text
            body = "\n".join(r.iter_lines())
        meta = _meta_of(body)
        assert meta["agent_mode"] is True
        assert "search_knowledge_base" in meta["agent_tools"]
        assert '"type": "agent_action"' in body or '"type":"agent_action"' in body
        assert "报销走线上流程" in body
        assert calls and calls[0]["tools"]

        import time
        time.sleep(2.5)  # 日志队列按 1 秒批次落库，留足余量
        rows = client.get("/api/admin/requests", headers=auth(admin_token),
                          params={"page": 1, "size": 5}).json()["items"]
        req = next(x for x in rows if x["conversation_id"] == meta["conversation_id"])
        assert req["status"] == "ok"

        detail = client.get(f"/api/admin/requests/{req['id']}", headers=auth(admin_token)).json()
        tool_spans = [s for s in detail["spans"] if s["kind"] == "tool"]
        assert len(tool_spans) == 1
        span = tool_spans[0]
        assert span["name"] == "search_knowledge_base"
        assert span["dur_ms"] == 42
        attrs = json.loads(span["attrs_json"])
        assert attrs["arguments"] == {"query": "报销流程"}
        assert attrs["status"] == "ok"
        assert attrs["count"] == 2
        assert attrs["sources"][0]["title"] == "报销制度"

        llm = next(s for s in detail["spans"] if s["kind"] == "llm")
        llm_attrs = json.loads(llm["attrs_json"])
        assert llm_attrs["agent_mode"] is True
        assert llm_attrs["agent_turns"] == 1
        assert llm["start_ms"] >= span["start_ms"] + span["dur_ms"]
    finally:
        cfg = cfgmod.load_config()
        for k, v in old.items():
            if v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v
        cfgmod.save_config(cfg)
